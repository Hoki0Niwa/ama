#include "tactics.h"
#include "transition.h"
#include "nuisance.h"
#include "physics.h"
#include "timing.h"
#include "disruption.h"
#include "../fever/stock.h"
#include "../fever/text.h"
#include "main_attack.h"
#include <chrono>
#include <cmath>
#include <limits>

// Normal board under threat: one search over the visible pieces, one value.
// Stacking, the smallest offset, firing the main chain and taking a drop are
// placements of the same search, compared by what they leave: the gauge
// reached, the links still ready to offset, the nuisance taken, the puyos
// spent. A drop on unknown columns is weighed on every column choice and not
// searched past; the caller observes the real board before the next piece.
namespace fever_battle {
using json = nlohmann::json;
namespace {
struct Weights {
    i64 entry, gauge, stock, color, drop, consume, mainline, height, early, builder, step, exposed, pending, uncountered, mainline_min;
    i64 arrival_pieces, fever_reach, growth_cells, harass, all_clear, disrupt;
    explicit Weights(const json& j):
        entry(number(j, "entry", 0, 1000000)), gauge(number(j, "gauge", 0, 1000000)),
        stock(number(j, "stock", 0, 1000000)), color(number(j, "color", 0, 1000000)),
        drop(number(j, "drop", 0, 1000000)), consume(number(j, "consume", 0, 1000000)),
        mainline(number(j, "mainline", 0, 1000000)), height(number(j, "height", 0, 1000000)),
        early(number(j, "early", 0, 1000000)), builder(number(j, "builder", 0, 1000000)),
        step(number(j, "step", 0, 1000000)), exposed(number(j, "exposed", 0, 1000000)),
        pending(number(j, "pending", 0, 1000000)), uncountered(number(j, "uncountered", 0, 1000000)),
        mainline_min(number(j, "mainline_min", 1, 19)), arrival_pieces(j.contains("arrival_pieces") ? number(j, "arrival_pieces", 0, 100) : 2),
        fever_reach(j.contains("fever_reach") ? number(j, "fever_reach", 0, 1000000) : 100),
        growth_cells(j.contains("growth_cells") ? number(j, "growth_cells", 1, 100) : 6),
        harass(j.contains("harass") ? number(j, "harass", 0, 1000000) : 400),
        all_clear(j.contains("all_clear") ? number(j, "all_clear", 0, 1000000) : 5000),
        disrupt(j.contains("disrupt") ? number(j, "disrupt", 0, 1000000) : 3000) {}
};
struct Node {
    Field field;
    i64 fixed = 0, flying = 0, remainder = 0;
    EnemyTrays enemy;
    i64 enemy_remainder = 0;
    int event = 0, frame = 0, phase = 0, gauge = 0;
    int popped = 0, dropped = 0, early = 0, early_gauge = 0, steps = 0, fire_delay = 0;
    bool builder_fire = false;      // the builder's own fire that leaves nothing pending
    bool fired_main = false;        // main: attack leaves fewer than max(24, half the starting cells)
    bool crush = false;            // main crush: <=2 links, 24 cells and column heights retained
    bool side_attack = false;      // a low-redundancy attack preserving the remaining board
    bool cleared = false;           // a placement cleared the whole board
    bool mistimed_attack = false;   // do not fund an early clear with a later timed attack
    int sent_end = -1;              // frame at which the last chain that sent nuisance ended (it is confirmed then)
};
// What one placement did, for the reply. Boards on unknown columns are kept
// only to be weighed; none of them becomes the next board.
struct Step {
    int chain = 0, dropped = 0, redundancy = 0;
    bool main = false, side = false;
    std::vector<i64> points;
    json links = json::array();
    i64 cancelled = 0, sent = 0;
    bool all_clear = false, due = false, board_known = true;
    Field cleared;                  // after the chain, before any drop
    std::vector<Field> boards;      // every board an unknown drop can leave
};
struct Outcome { bool alive = false; i64 value = 0; int gauge = 0; i64 sent = 0; double kills = 0; double disrupt = 0; bool cleared = false; std::string disruption_kind = "none"; bool useful_harass = false; };
struct Exhausted {};
// Gauge gain depends on links that actually offset, not the chain's length.
struct GaugeResponse {
    int gauge = 0, gain = 0, rate = 120;
    i64 remainder = 0;
    std::vector<std::vector<i64>> counters;
    explicit GaugeResponse(const json& j = json::object()) {
        if (!j.contains("counter_points")) return;
        gauge = number(j, "gauge", 0, 7);
        gain = j.contains("offset_gain") ? number(j, "offset_gain", 0, 7) : 1;
        rate = number(j, "rate", 1, 100000);
        remainder = number(j, "remainder", 0, 1000000000);
        const auto& rows = j.at("counter_points");
        if (!rows.is_array() || rows.size() > 64) throw std::invalid_argument("invalid counter profiles");
        for (const auto& row : rows) {
            if (!row.is_array() || row.size() > 19) throw std::invalid_argument("invalid counter chain");
            std::vector<i64> points;
            for (const auto& p : row) {
                if (!p.is_number_integer() || p < 0 || p > 1000000000) throw std::invalid_argument("invalid counter score");
                points.push_back(p.get<i64>());
            }
            counters.push_back(std::move(points));
        }
    }
    bool can_enter(i64 pending) const {
        if (!gain || !pending) return false;
        for (const auto& points : counters) {
            i64 left = pending, rest = remainder; int after = gauge;
            for (const auto p : points) {
                if (!left) break;
                const i64 sum = p + rest; rest = sum % rate;
                const i64 offset = std::min(left, std::max<i64>(1, sum / rate));
                left -= offset; after = std::min(7, after + gain);
            }
            if (after >= 7) return true;
        }
        return false;
    }
};
// Pieces a main chain is taken to have for growing when nothing presses it to fire.

class Search {
public:
    std::vector<piece::Piece> pieces;
    std::vector<int> powers;
    Bonuses bonuses;
    json events = json::array();
    const RateSchedule* rates = nullptr;
    const Weights* w = nullptr;
    rule::Rule rules = rule::FEVER;
    bool unknown_phase = false, geometry = false;
    int root_cells = 0;
    int gain = 1, root_gauge = 0, width = 16, expanded = 0, max_nodes = 1500;
    int placement = 14, pop = 55, settle = 14, fall = 2, spawn = 28, score_offset = 0;
    int first_link = 0, chain_ready = 0, check = 0;
    i64 enemy_hold = 0;             // nuisance the opponent can still send with what they hold
    Defense defense;                // what they have against nuisance that lands (transition.h)
    GaugeResponse response;
    // The opponent is in Fever (or about to enter it). Nuisance confirmed for them there has to be met
    // with the next piece or it falls on the seed: a packet that is waiting when a new seed arrives
    // disrupts for sure, one that arrives while they build on a seed makes them fire early.
    // their_end: frame at which their running chain ends and the next seed comes (0: a seed is about
    // to come, -1: none of that is observed). window: frames after it within which a packet is waiting.
    bool enemy_fever = false;
    i64 enemy_after_chain = 0;       // existing packets after their attack, without our new send
    int their_end = -1, window = 26;
    i64 seed_reply = 0;
    bool skip_jab = false;
    bool current_attack = false;
    json seed_defense = json::array();
    bool extending = false;
    int pace = 0;                   // frames this side takes per piece, when the caller has measured it
    int piece_frames() const { return std::max(placement + spawn, pace); }
    std::string upcoming;           // shapes of the pieces after the visible ones, by the character's cycle
    // quiet: no packet is pending. A clear then is not an offset spent early;
    // it costs the puyos it takes from the main chain's growth. harass: the
    // builder's own move for this piece is a small clear, and a clear that
    // leaves the main chain whole is credited with what it sends instead, so
    // that the puyos go into an attack. Nothing is credited at an opponent who
    // holds more than this board does.
    bool quiet = false, harass = false, invite_fever = false, avoid_own_fever = false;
    i64 own_hold = 0, root_sent = 0;
    double pressure = 1.0;

    // Use the observed column cursor in every risk estimate, as in play().
    template <class Visit>
    void drops(const Field& field, int count, int phase, Visit visit) const {
        if (unknown_phase) each_remainder_drop(field, count, visit);
        else { auto board = field; drop_nuisance(board, count, phase); visit(board); }
    }
    json split_costs = json::array();

    void advance(Node& n, int until) const {
        advance_enemy(events, *rates, until, n.event, n.fixed, n.flying,
            n.enemy, n.enemy_remainder);
        n.frame = until;
    }
    void tick() {
        // The placement count bounds the search, so that the same request gets
        // the same answer without a wall-clock cutoff.
        if (++expanded > max_nodes) throw Exhausted{};
    }
    // Plays one placement. False when the piece cannot go there.
    bool play(Node& n, const piece::Piece& piece, const move::Placement& move, Step& step) const {
        advance(n, n.frame + placement);
        auto splits = split_distances(n.field, piece, move.x, move.r);
        const int rows = *std::max_element(splits.begin(), splits.end());
        const int extra = !split_costs.empty() && !split_costs[rows].is_null()
            ? split_costs[rows].get<int>() : rows * fall;
        if (!n.field.drop_piece(move.x, move.r, piece, rules)) return false;
        advance(n, n.frame + extra);
        // A clear is due when popping nothing would let nuisance fall now, or
        // would leave a board that what is pending kills whenever it lands.
        {
            auto peek = n; advance(peek, peek.frame + check);
            step.due = peek.fixed > 0;
            const int pending = int(std::min<i64>(30, peek.fixed + peek.flying));
            if (!step.due && pending)
                drops(n.field, pending, n.phase, [&](Field board) { step.due = step.due || board.is_dead(rules); });
        }
        const auto locked = n.field;
        auto masks = n.field.pop();
        step.chain = masks.get_size();
        step.cleared = n.field;
        step.all_clear = step.chain && n.field.is_empty();
        ++n.steps;
        const int gauge_before = n.gauge;
        if (step.chain) {
            const int start = n.frame;
            // ai/ai.cpp on main: classify by the resources left, not by chain length.
            step.main = step.cleared.get_count() < std::max(24, root_cells / 2);
            auto before = locked, after = step.cleared;
            step.redundancy = gaze::get_redundancy(before, after);
            step.side = !step.main && step.redundancy <= 4;
            n.fired_main = n.fired_main || step.main;
            n.side_attack = n.side_attack || step.side;
            u8 left[6]; after.get_heights(left);
            n.crush = n.crush || (step.side && step.chain <= 2 && left[0] >= 4 && left[1] >= 4 && left[2] >= 4
                && left[3] >= 3 && left[4] >= 3 && left[5] >= 3);
            const auto features = fall_features(locked, masks);
            const auto falls = fall_distances(locked, masks);
            advance(n, n.frame + first_link);
            for (int i = 0; i < step.chain; ++i) {
                const auto link = score_link(masks[i], powers.at(i), bonuses);
                n.popped += link.cells;
                step.points.push_back(link.points);
                step.links.push_back({{"groups", link.groups}, {"colors", link.colors}});
                advance(n, n.frame + score_offset);
                i64 total = link.points + n.remainder;
                const int rate = rates->at(n.frame);
                i64 amount = total / rate; n.remainder = total % rate;
                if (n.fixed + n.flying && amount == 0) amount = 1;
                i64 taken = std::min(n.fixed, amount); n.fixed -= taken; amount -= taken;
                i64 more = std::min(n.flying, amount); n.flying -= more; amount -= more;
                if (taken + more) n.gauge = std::min(7, n.gauge + gain);
                step.cancelled += taken + more; step.sent += amount;
                n.enemy.send(amount, n.frame);
                const int duration = geometry ? link_frames(features[i], i == step.chain - 1)
                    : pop + settle + falls[i] * fall;
                advance(n, n.frame + duration - score_offset);
            }
            if (step.sent > 0) {
                n.sent_end = n.frame;
                if (enemy_fever && !disruption::timed(n.sent_end, their_end, window)) n.mistimed_attack = true;
            }
            n.cleared = n.cleared || step.all_clear;
            n.enemy.confirm();
            // Nothing was about to fall: the same offsets stay available later,
            // so a clear made now earns no credit unless it enters Fever.
            if (!step.due && n.gauge < 7) { ++n.early; n.early_gauge += n.gauge - gauge_before; }
            advance(n, n.frame + chain_ready);
            n.fire_delay += std::max(0, n.frame - start - spawn);
            return true;
        }
        advance(n, n.frame + check);
        step.dropped = int(std::min<i64>(30, n.fixed));
        n.fixed -= step.dropped; n.dropped += step.dropped;
        if (unknown_phase && step.dropped % 6) {
            step.board_known = false;
            each_remainder_drop(n.field, step.dropped, [&](Field board) { step.boards.push_back(board); });
        } else {
            drop_nuisance(n.field, step.dropped, n.phase);
        }
        n.phase = (n.phase + step.dropped) % 6;
        advance(n, n.frame + std::max(0, spawn - check));
        return true;
    }
    // Pieces that can still fire before what is pending falls: the next one
    // when it is confirmed (it falls on a placement that pops nothing), that
    // and as many as fit before the observed chain ends, or the policy's guess
    // when nothing tells when an unconfirmed packet lands.
    int pieces_before_drop(const Node& n) const {
        if (n.fixed > 0) return 1;
        for (int i = n.event; i < int(events.size()); ++i)
            if (events[i]["type"] == "end")
                return 1 + std::max(0, events[i]["frame"].get<int>() - n.frame) / piece_frames();
        return int(w->arrival_pieces);
    }
    // Nuisance the observed chain has yet to send.
    i64 future(const Node& n) const {
        i64 points = 0;
        for (int i = n.event; i < int(events.size()); ++i)
            if (events[i]["type"] == "link") points += events[i]["points"].get<i64>();
        return points / rates->at(n.frame, true);
    }
    // How far what is left lies beyond what a Fever can still turn around:
    // half way at the reach, where the turn is a chance and no more, and
    // all the way from twice the reach.
    double beyond(i64 left) const {
        if (w->fever_reach <= 0) return left > 0 ? 1.0 : 0.0;
        return std::clamp(double(left) / double(2 * w->fever_reach), 0.0, 1.0);
    }
    // The value of stopping here.
    Outcome leaf(const Node& n) const {
        auto field = n.field;
        if (field.is_dead(rules)) return {false, -1000000000 + i64(n.steps) * 1000, n.gauge};
        const bool entered = n.gauge >= 7;
        const auto stock = fever::stock::evaluate(field, std::max(1, 7 - n.gauge));
        i64 value = (enemy_fever && !avoid_own_fever ? i64(double(n.gauge - root_gauge - (entered ? 0 : n.early_gauge)) * w->gauge * pressure) : 0)
            - i64(n.dropped) * w->drop - i64(n.popped) * w->consume - i64(n.steps) * w->step
            - std::min<i64>(60, n.fixed + n.flying) * w->pending;
        // What still comes at this board, and what the opponent answers with
        // once what was sent to them is taken off what they hold.
        const i64 arriving = n.fixed + n.flying + future(n);
        const i64 answer = std::max<i64>(0, enemy_hold - n.enemy.pending());
        // Nuisance that lands on an opponent who cannot fill the gauge in time
        // ends the game, whatever was broken to send it; one about to enter
        // Fever is not killed, and there only what the chain scores counts.
        // What is on them once their observed chain has run out: its remaining links first offset it.
        i64 on_them = n.enemy.total();
        {
            auto index = n.event; i64 mine = 0, flying = 0, rest = n.enemy_remainder; auto theirs = n.enemy;
            advance_enemy(events, *rates, std::numeric_limits<int>::max(), index, mine, flying, theirs, rest);
            on_them = enemy_fever ? theirs.seed() : theirs.normal();
        }
        const bool timed_attack = disruption::timed(n.sent_end, their_end, window) && !n.mistimed_attack;
        // The normal builder owns the target/capacity fire policy. A future
        // main in the tactical horizon must not pay for breaking that build
        // now, even if one low seed can be beaten by a short main.
        const bool unready_main = enemy_fever && n.fired_main && !n.builder_fire;
        const bool protected_main = (unready_main || (quiet && n.fired_main && !n.builder_fire)) && root_cells >= 24;
        const double kills = 0.0; // Kill estimates are not an attack objective in Fever battles.
        // A packet of this line's own, left on a Fever opponent after their chain.
        i64 reply_capacity=seed_reply; bool counter_unknown=false;
        if(extending && seed_defense.size()==31) {
            const auto& counter=seed_defense[std::min<i64>(30,on_them)];
            if(counter.value("checked",false) && counter.value("regular_after_drop",false)) {
                reply_capacity=std::max(reply_capacity,counter.value("reply_nuisance",seed_reply));
                counter_unknown=!counter.value("counter_complete",false);
            }
        }
        auto disruption = enemy_fever ? disruption::rate(on_them, enemy_after_chain, reply_capacity,
            timed_attack, n.side_attack || root_cells < 24, skip_jab, n.fired_main, current_attack && n.side_attack,
            !unready_main) : disruption::Rating{};
        if (enemy_fever && extending && on_them > enemy_after_chain && n.sent_end >= 0 && seed_defense.size()==31) {
            if(counter_unknown && std::string(disruption.kind)!="jab") disruption={};
            const auto& response=seed_defense[std::min<i64>(30,on_them)];
            const auto& existing=seed_defense[std::min<i64>(30,enemy_after_chain)];
            const bool already_blocked=enemy_after_chain>0 && existing.value("checked",false) && !existing.value("regular_after_drop",false);
            const auto pressure=disruption::extension(on_them-enemy_after_chain,(n.side_attack || root_cells<24) && !already_blocked,
                response.value("checked",false),response.value("regular_after_drop",false),skip_jab);
            if(pressure.value>disruption.value) disruption=pressure;
        }
        if (protected_main) disruption = {};
        const double disrupts = disruption.value;
        value += i64(disrupts * double(w->disrupt));
        // The board cleared: under the Fever rule a four-chain seed drops for it (and the Fever clock
        // gains). It is worth less the more the opponent can still send at the board it leaves.
        if (n.cleared && !protected_main) value += i64(double(w->all_clear) * (1.0 - beyond(answer)));
        bool useful_harass = false;
        if (quiet && harass && n.crush && !n.fired_main && enemy_hold <= own_hold) {
            const i64 sent = n.enemy.total() - root_sent;
            const bool entry = response.can_enter(on_them);
            // Before either side has entered Fever, a small shot can invite
            // their entry, leaving our main chain ready for the Fever board.
            if (entry && invite_fever && sent > 0 && own_hold > 0) {
                value += std::min<i64>(sent + 6, 30) * w->harass;
                useful_harass = w->harass > 0;
            }
        }
        const i64 sent_here = n.enemy.total() - root_sent;
        if (entered) return {true, value + (avoid_own_fever ? -w->entry : enemy_fever ? i64(w->entry * pressure)
            : (n.fired_main || n.builder_fire ? 0 : -w->entry)), n.gauge, sent_here, kills, disrupts, n.cleared && !protected_main, disruption.kind, useful_harass};
        u8 heights[6]; field.get_heights(heights);
        value += stock.units * w->stock + stock.colors * w->color
            - i64(std::max(0, int(std::max(heights[2], heights[3])) - 8)) * w->height
            - (quiet ? 0 : i64(n.early) * w->early);
        // Nuisance still pending falls on the next placement that pops nothing.
        // A board it would kill is held only by a trigger: the fewer colors
        // fire one with a single puyo, the more it rests on the next piece.
        const int pending = int(std::min<i64>(30, n.fixed + n.flying));
        bool stands = true;
        if (pending) {
            drops(field, pending, n.phase, [&](Field board) { stands = stands && !board.is_dead(rules); });
            if (!stands) value -= w->exposed * (4 - std::min(3, stock.colors));
        }
        return {true, value, n.gauge, sent_here, kills, disrupts, n.cleared && !protected_main, disruption.kind, useful_harass};
    }
    // The worst board an unknown drop can leave.
    Outcome leaf(const Node& n, const Step& step) const {
        if (step.board_known) return leaf(n);
        Outcome worst; bool first = true;
        for (const auto& board : step.boards) {
            auto copy = n; copy.field = board;
            const auto value = leaf(copy);
            if (first || std::make_pair(value.alive, value.value) < std::make_pair(worst.alive, worst.value)) worst = value;
            first = false;
        }
        return worst;
    }
    // Whether the search goes on below a placement.
    bool ends(const Node& n, const Step& step, int depth, int limit) const {
        return depth + 1 >= limit || depth + 1 >= int(pieces.size()) || n.gauge >= 7 || n.fired_main || n.builder_fire ||
            step.all_clear || !step.board_known;
    }
    Outcome below(const Node& n, const Step& step, int depth, int limit) {
        const auto here = leaf(n, step);
        if (!here.alive || here.disrupt >= 1 || ends(n, step, depth, limit)) return here;
        return solve(n, depth + 1, limit);
    }
    Outcome solve(const Node& node, int depth, int limit) {
        struct Child { Node node; Step step; Outcome here; };
        std::vector<Child> children;
        auto field = node.field;
        auto moves = move::generate(field, pieces[depth], rules);
        for (int i = 0; i < moves.get_size(); ++i) {
            tick();
            Child child{node, {}, {}};
            if (!play(child.node, pieces[depth], moves[i], child.step)) continue;
            child.here = leaf(child.node, child.step);
            if (child.here.alive) children.push_back(std::move(child));
        }
        if (children.empty()) return {false, -1000000000 + i64(node.steps) * 1000, node.gauge};
        std::stable_sort(children.begin(), children.end(), [](const Child& a, const Child& b) {
            return a.here.value > b.here.value;
        });
        if (children.size() > size_t(width)) children.resize(width);
        Outcome best; bool first = true;
        for (const auto& child : children) {
            const auto value = below(child.node, child.step, depth, limit);
            if (first || std::make_pair(value.alive, value.value) > std::make_pair(best.alive, best.value)) best = value;
            first = false;
        }
        return best;
    }
};
}

json tactics(Field field, const json& request) {
    Search search;
    search.rules.plain_pairs = true; search.rules.special_moves = true;
    if (field.is_dead(search.rules)) throw std::invalid_argument("already dead field");
    const auto queue = request.at("queue").get<std::vector<std::string>>();
    if (queue.empty() || queue.size() > 3) throw std::invalid_argument("visible queue only");
    for (const auto& text : queue) {
        auto piece = fever::text::to_piece(text);
        if (!piece) throw std::invalid_argument("invalid visible piece");
        search.pieces.push_back(*piece);
    }
    const auto& powers = request.at("powers");
    if (!powers.is_array() || powers.size() != 19) throw std::invalid_argument("19 normal powers required");
    search.powers = powers.get<std::vector<int>>();
    search.bonuses = Bonuses(request.at("bonuses"));
    search.events = request.value("enemy_events", json::array());
    if (!search.events.is_array()) throw std::invalid_argument("enemy_events must be an array");
    int previous = -1;
    for (const auto& event : search.events) {
        const int at = number(event, "frame", 0, 1000000);
        if (at < previous) throw std::invalid_argument("enemy events must be ordered");
        previous = at;
        if (event.at("type") != "end") {
            if (event.at("type") != "link") throw std::invalid_argument("unknown enemy event");
            number(event, "points", 0, 1000000000);
        }
    }
    const int rate = number(request, "target_point", 1, 100000);
    const RateSchedule rates(request, rate);
    const Weights weights(request.at("weights"));
    search.rates = &rates; search.w = &weights;
    search.gain = number(request, "gain", 1, 7);
    search.width = number(request, "width", 1, 64);
    search.max_nodes = number(request, "max_nodes", 1, 1000000);
    search.unknown_phase = request.value("unknown_garbage_phase", false);
    search.enemy_hold = request.contains("enemy_hold") ? number(request, "enemy_hold", 0, 1000000000) : 0;
    search.upcoming = request.value("upcoming", std::string());
    if (request.contains("enemy_defense")) {
        search.defense = Defense(request.at("enemy_defense"));
        search.response = GaugeResponse(request.at("enemy_defense"));
        search.enemy_hold = search.defense.hold;
    }
    // What they can still send (all their seeds, the chain of the board they return to) can be more
    // than what the seed in hand offsets; told apart where the caller has both.
    if (request.contains("enemy_hold")) search.enemy_hold = number(request, "enemy_hold", 0, 1000000000);
    search.pace = request.contains("pace_frames") ? number(request, "pace_frames", 1, 10000) : 0;
    search.harass = request.value("harass", false);
    search.invite_fever = request.value("invite_fever", false);
    search.avoid_own_fever = request.value("avoid_own_fever", false);
    search.quiet = request.value("quiet", false);
    search.enemy_fever = request.value("enemy_fever", false);
    search.seed_reply = request.contains("enemy_reply_nuisance") ? number(request, "enemy_reply_nuisance", 0, 1000000000) : search.defense.hold;
    search.skip_jab = request.value("enemy_skip_jab", false);
    search.current_attack = std::any_of(search.events.begin(), search.events.end(), [](const json& e) {
        return e.at("type") == "link" && e.value("points", i64(0)) > 0;
    });
    search.extending = request.value("enemy_extending",false);
    search.seed_defense = request.value("enemy_seed_defense",json::array());
    search.their_end = request.contains("their_end") ? number(request, "their_end", 0, 1000000) : -1;
    search.window = request.contains("disrupt_window") ? number(request, "disrupt_window", 0, 100000) : disruption::WINDOW;
    const auto& timing = request.at("timing");
    search.placement = number(timing, "placement_frames", 1, 10000);
    search.pop = number(timing, "pop_frames", 1, 10000);
    search.settle = number(timing, "settle_frames", 0, 10000);
    search.fall = number(timing, "fall_frames_per_row", 0, 10000);
    search.spawn = number(timing, "spawn_frames", 0, 10000);
    search.score_offset = timing.contains("score_offset_frames")
        ? number(timing, "score_offset_frames", 0, search.pop) : search.pop;
    search.geometry = timing.value("geometry_timing", false);
    search.first_link = timing.contains("first_link_frames") ? number(timing, "first_link_frames", 0, 10000) : 0;
    search.chain_ready = timing.contains("chain_ready_frames")
        ? number(timing, "chain_ready_frames", 0, 10000) : search.spawn;
    search.check = timing.value("nuisance_check_frames", 0);
    search.split_costs = timing.value("split_extra_frames", json::array());
    if (!search.split_costs.empty() && (!search.split_costs.is_array() || search.split_costs.size() != 14))
        throw std::invalid_argument("split duration table must have 14 entries");

    Node root; root.field = field;
    root.fixed = number(request, "confirmed", 0, 1000000000);
    root.flying = number(request, "unconfirmed", 0, 1000000000);
    root.remainder = number(request, "remainder", 0, 1000000000);
    root.phase = number(request, "garbage_phase", 0, 5);
    root.gauge = number(request, "gauge", 0, 6);
    root.enemy = EnemyTrays(request);
    root.enemy_remainder = request.contains("enemy_remainder") ? number(request, "enemy_remainder", 0, 1000000000) : 0;
    search.root_gauge = root.gauge;
    search.root_cells = field.get_count();
    const auto root_stock = fever::stock::evaluate(field, 7 - root.gauge);
    search.root_sent = root.enemy.total();
    {
        auto baseline = root;
        advance_enemy(search.events, rates, std::numeric_limits<int>::max(), baseline.event,
            baseline.fixed, baseline.flying, baseline.enemy, baseline.enemy_remainder);
        search.enemy_after_chain = search.enemy_fever ? baseline.enemy.seed() : baseline.enemy.normal();
    }
    // Gauge is insurance against a packet that needs Fever. A few nuisance
    // on a low board are not worth entering Fever or consuming the build for.
    search.pressure = std::min(1.0, double(root.fixed + root.flying + search.future(root)) / 30.0);
    search.drops(field, int(std::min<i64>(30, root.fixed + root.flying + search.future(root))), root.phase,
        [&](Field board) { if (board.is_dead(search.rules)) search.pressure = 1.0; });
    if (search.quiet) search.own_hold = main_attack::potential(field, search.powers, search.bonuses).first / rate;

    // The builder's own placement: it knows the build further ahead than the
    // visible pieces. Where it pops, it is the builder firing by its own
    // policy, which stands when it leaves nothing pending.
    const auto by_builder = [&](const move::Placement& move) {
        if (!request.contains("builder")) return false;
        const auto& b = request.at("builder");
        return b.at("x") == move.x && b.at("r") == std::string(1, fever::text::from_direction(move.r));
    };
    struct First { move::Placement move; Node node; Step step; Outcome here; i64 bonus = 0; };
    std::vector<First> firsts;
    auto moves = move::generate(field, search.pieces[0], search.rules);
    for (int i = 0; i < moves.get_size(); ++i) {
        const auto r = std::string(1, fever::text::from_direction(moves[i].r));
        if (request.contains("allowed")) {
            bool allowed = false;
            for (const auto& m : request.at("allowed")) allowed |= m.at("x") == moves[i].x && m.at("r") == r;
            if (!allowed) continue;
        }
        First first{moves[i], root, {}, {}};
        if (!search.play(first.node, search.pieces[0], moves[i], first.step)) continue;
        if (by_builder(moves[i]) && (!first.step.chain || first.node.fixed + first.node.flying == 0)) {
            first.bonus = weights.builder;
            first.node.early = 0; first.node.early_gauge = 0;
            first.node.builder_fire = first.step.chain > 0 &&
                request.at("builder").value("fire", false);
        }
        first.here = search.leaf(first.node, first.step);
        firsts.push_back(std::move(first));
    }
    if (firsts.empty()) throw std::invalid_argument("no conservative legal placement");
    // The tactical override must respect the builder's room for input error.
    // Relax only when every surviving placement already exceeds that margin.
    const int margin = request.contains("margin") ? number(request, "margin", 0, 6) : 1;
    const auto safe = [&](const First& first) {
        u8 heights[6]; auto board = first.node.field; board.get_heights(heights);
        return first.here.alive && std::max(heights[2], heights[3]) <= 11 - margin;
    };
    if (std::any_of(firsts.begin(), firsts.end(), safe))
        std::erase_if(firsts, [&](const First& first) { return !safe(first); });
    std::vector<Outcome> values(firsts.size());
    int completed = 0; bool cutoff = false, skipped = false;
    try {
        for (int limit = 1; limit <= int(search.pieces.size()); ++limit) {
            // A deeper pass is started only when the placements left can finish it:
            // one cut off half way is thrown away, and its time with it.
            // Narrow the last pass to fit all root moves rather than never
            // looking at NEXT2. Count each future shape's legal upper bound;
            // triples and big puyos need not have the current piece's count.
            const auto required = [&]() {
                i64 nodes = 1, branches = 1;
                for (int d = 1; d < limit; ++d) {
                    auto empty = Field();
                    const int count = move::generate(empty, search.pieces[d], search.rules).get_size();
                    nodes += branches * count;
                    branches *= std::min(search.width, count);
                }
                return nodes * i64(firsts.size());
            };
            while (limit > 2 && search.width > 1 && required() > i64(search.max_nodes) - search.expanded)
                --search.width;
            const i64 needed = required();
            if (limit > 1 && needed > i64(search.max_nodes) - search.expanded) { skipped = true; break; }
            std::vector<Outcome> layer(firsts.size());
            for (size_t i = 0; i < firsts.size(); ++i) {
                search.tick();
                layer[i] = search.below(firsts[i].node, firsts[i].step, 0, limit);
                layer[i].value += firsts[i].bonus;
            }
            values = std::move(layer); completed = limit;
        }
    } catch (const Exhausted&) { cutoff = true; }
    if (!completed) {
        // Not even one piece was weighed within the budget: every placement by itself.
        for (size_t i = 0; i < firsts.size(); ++i) {
            values[i] = firsts[i].here; values[i].value += firsts[i].bonus;
        }
    }
    // Port main ai.cpp steps 2, 5, 6, 7, 8 to Fever placements/timing. The
    // underlying main gaze helpers are unchanged; special shapes and nuisance
    // simulation stay in the Fever search. Initial/second build targets stay
    // with the builder, as configured by the user.
    std::optional<size_t> counter;
    auto baseline = root;
    search.advance(baseline, std::numeric_limits<int>::max());
    const i64 incoming = baseline.fixed + baseline.flying;
    auto acceptance_board = field;
    const int accept_limit = gaze::get_accept_limit(acceptance_board);
    // Being in Fever does not make every small packet an urgent counter.
    // Keep building when the ordinary resource/height acceptance permits it.
    const bool accept = incoming <= accept_limit && field.get_height(2) < 10;
    const auto points = [&](size_t i) {
        i64 sum = 0; for (auto p : firsts[i].step.points) sum += p; return sum;
    };
    const auto earlier = [&](size_t a, size_t b) {
        return firsts[a].node.frame < firsts[b].node.frame;
    };
    // First an executable sufficient return. A large attack can justify
    // immediate firing; otherwise prefer the small response that preserves
    // resources before spending the main chain.
    if (incoming > 0) {
        std::vector<size_t> full, small, mains, desperate, entry_returns;
        for (size_t i = 0; i < firsts.size(); ++i) {
            const auto& f = firsts[i];
            if (!values[i].alive || !f.step.chain) continue;
            // Do not spend a weak main before the observed Fever attack has
            // arrived: waiting lets its links actually offset and gain gauge.
            if (search.enemy_fever && f.step.main && f.step.cancelled == 0
                    && values[i].disrupt < 0.5 && points(i) / rate <= search.seed_reply
                    && root.fixed + root.flying == 0) continue;
            const i64 send = points(i) / rate;
            if (send >= incoming) {
                if (search.enemy_fever && !search.avoid_own_fever && root.gauge < 7 && f.node.gauge >= 7 && f.step.side)
                    entry_returns.push_back(i);
                if (points(i) >= 2100 && (incoming >= 90 || points(i) >= std::min<i64>(request.value("main_trigger_points", i64(85000)), 85000))) full.push_back(i);
                if (f.step.main) mains.push_back(i); else small.push_back(i);
            } else if (send + 30 >= incoming) desperate.push_back(i);
        }
        const auto pick = [&](const std::vector<size_t>& group, bool small_return) {
            for (const auto i : group) {
                if (!counter) { counter = i; continue; }
                const auto j = *counter;
                if (search.avoid_own_fever && (firsts[i].node.gauge >= 7) != (firsts[j].node.gauge >= 7)) {
                    if (firsts[i].node.gauge < 7) counter = i;
                } else if (small_return && (firsts[i].step.redundancy > 4) != (firsts[j].step.redundancy > 4)) {
                    if (firsts[i].step.redundancy <= 4) counter = i;
                } else if (!small_return && points(i) / rate >= incoming + 90 && points(j) / rate >= incoming + 90) {
                    if (earlier(i, j) || (firsts[i].node.frame == firsts[j].node.frame && points(i) > points(j))) counter = i;
                } else if (!small_return && (points(i) / rate >= incoming + 90) != (points(j) / rate >= incoming + 90)) {
                    if (points(i) / rate >= incoming + 90) counter = i;
                } else if (std::abs(points(i) - points(j)) / rate >= 6) {
                    if (points(i) > points(j)) counter = i;
                } else if (earlier(i, j)) counter = i;
            }
        };
        // In a Fever battle a sufficient small return that fills our gauge
        // preserves the main chain. Normal opponents keep main's priorities.
        pick(entry_returns, true);
        if (!counter && !(search.avoid_own_fever && accept)) pick(full, false);
        if (!counter && !accept) pick(small, true);
        if (!counter && !accept) pick(mains, false);
        if (!counter && !accept && (root.fixed > 0 || search.pieces_before_drop(root) <= 1))
            pick(desperate, false);
    }
    json candidates = json::array();
    size_t best = 0;
    for (size_t i = 0; i < firsts.size(); ++i) {
        auto& first = firsts[i];
        if (std::make_pair(values[i].alive, values[i].value) > std::make_pair(values[best].alive, values[best].value)) best = i;
        auto shown = first.step.board_known ? first.node.field : first.step.cleared;
        candidates.push_back({{"x", first.move.x}, {"r", std::string(1, fever::text::from_direction(first.move.r))},
            {"attack_kind", !first.step.chain ? "build" : first.step.main ? "main" : "side"},
            {"redundancy", first.step.redundancy}, {"remaining_cells", first.step.cleared.get_count()},
            {"chain", first.step.chain}, {"links", first.step.links}, {"link_points", first.step.points},
            {"cancelled", first.step.cancelled}, {"sent", first.step.sent}, {"dropped", first.step.dropped},
            {"drop_due", first.step.due}, {"all_clear", first.step.all_clear},
            {"gauge_after", first.node.gauge}, {"projected_gauge", values[i].gauge}, {"projected_sent", values[i].sent}, {"projected_kill", values[i].kills},
            {"gauge_before", root.gauge}, {"enters_fever", root.gauge < 7 && first.node.gauge >= 7},
            {"opponent_entry_possible", !search.enemy_fever && search.response.can_enter(first.node.enemy.normal())},
            {"invites_opponent_fever", search.invite_fever && first.node.crush && first.step.sent > 0
                && search.own_hold > 0 && search.enemy_hold <= search.own_hold
                && search.response.can_enter(first.node.enemy.normal())},
            {"attack_end", first.node.sent_end}, {"enemy_trays", first.node.enemy.json()},
            {"projected_disrupt", values[i].disrupt}, {"projected_all_clear", values[i].cleared},
            {"projected_harass", values[i].useful_harass},
            {"disruption_kind", values[i].disruption_kind},
            {"survives", values[i].alive}, {"value", values[i].value},
            {"post_drop_field_known", first.step.board_known},
            {"possible_drop_boards", first.step.board_known ? 1 : int(first.step.boards.size())},
            {"field", fever::text::from_field(shown)},
            {"confirmed", first.node.fixed}, {"unconfirmed", first.node.flying},
            {"remainder", first.node.remainder}, {"frame", first.node.frame}});
    }
    bool held_main = false;
    const bool weak_builder = std::any_of(firsts.begin(), firsts.end(), [&](const First& f) {
        i64 sum = 0; for (auto p : f.step.points) sum += p;
        return f.node.builder_fire && f.step.main && !f.step.all_clear && sum / rate <= search.seed_reply;
    });
    if (incoming == 0 && search.enemy_fever && search.root_cells >= 24
            && weak_builder && !firsts[best].step.chain) held_main = true;
    if (!counter && incoming == 0 && search.enemy_fever && search.root_cells >= 24
            && firsts[best].step.main && !firsts[best].step.all_clear
            && values[best].disrupt < 0.5 && points(best) / rate <= search.seed_reply) {
        std::optional<size_t> building;
        for (size_t i = 0; i < firsts.size(); ++i)
            if (safe(firsts[i]) && !firsts[i].step.chain && (!building || values[i].value > values[*building].value)) building = i;
        if (building) { best = *building; held_main = true; }
    }
    if (counter) best = *counter;
    else if (incoming > 0 && accept && firsts[best].step.chain
            && (!firsts[best].node.builder_fire || (search.avoid_own_fever && firsts[best].node.gauge >= 7))
            && !firsts[best].step.all_clear) {
        std::optional<size_t> building;
        for (size_t i = 0; i < firsts.size(); ++i)
            if (values[i].alive && !firsts[i].step.chain && (!building || values[i].value > values[*building].value)) building = i;
        if (building) best = *building;
    }
    return {{"choice", candidates[best]}, {"attack_policy", "main_resource_and_score"}, {"candidates", candidates},
        {"completed_depth", completed}, {"visible", queue.size()}, {"expanded", search.expanded}, {"cutoff", cutoff},
        {"deeper_pass_skipped", skipped}, {"held_main_for_counter", held_main},
        {"root_stock", {{"units", root_stock.units}, {"links", root_stock.links},
            {"colors", root_stock.colors}, {"longest", root_stock.longest}}},
        {"enemy_hold", search.enemy_hold}, {"harass", search.harass}, {"own_hold", search.own_hold},
        {"enemy_seed_at", search.their_end}, {"disrupt_window", search.window},
        {"unknown_drop_policy", "worst_column_choice_then_reobserve"},
        {"future_unconfirmed_arrival", search.events.empty() ? "unscheduled_not_dropped" : "predicted_chain_timeline"}};
}
}

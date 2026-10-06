#include "tactics.h"
#include "transition.h"
#include "physics.h"
#include "timing.h"
#include "../fever/stock.h"
#include "../fever/text.h"
#include <chrono>

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
    explicit Weights(const json& j):
        entry(number(j, "entry", 0, 1000000)), gauge(number(j, "gauge", 0, 1000000)),
        stock(number(j, "stock", 0, 1000000)), color(number(j, "color", 0, 1000000)),
        drop(number(j, "drop", 0, 1000000)), consume(number(j, "consume", 0, 1000000)),
        mainline(number(j, "mainline", 0, 1000000)), height(number(j, "height", 0, 1000000)),
        early(number(j, "early", 0, 1000000)), builder(number(j, "builder", 0, 1000000)),
        step(number(j, "step", 0, 1000000)), exposed(number(j, "exposed", 0, 1000000)),
        pending(number(j, "pending", 0, 1000000)), uncountered(number(j, "uncountered", 0, 1000000)),
        mainline_min(number(j, "mainline_min", 1, 19)) {}
};
struct Node {
    Field field;
    i64 fixed = 0, flying = 0, remainder = 0;
    i64 enemy_fixed = 0, enemy_flying = 0, enemy_remainder = 0;
    int event = 0, frame = 0, phase = 0, gauge = 0;
    int popped = 0, dropped = 0, early = 0, early_gauge = 0, steps = 0;
    bool builder_fire = false;      // the builder's own fire that leaves nothing pending
};
// What one placement did, for the reply. Boards on unknown columns are kept
// only to be weighed; none of them becomes the next board.
struct Step {
    int chain = 0, dropped = 0;
    std::vector<i64> points;
    json links = json::array();
    i64 cancelled = 0, sent = 0;
    bool all_clear = false, due = false, board_known = true;
    Field cleared;                  // after the chain, before any drop
    std::vector<Field> boards;      // every board an unknown drop can leave
};
struct Outcome { bool alive = false; i64 value = 0; int gauge = 0; };
struct Exhausted {};

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
    int gain = 1, root_gauge = 0, root_longest = 0, width = 16, expanded = 0, max_nodes = 6000;
    int placement = 14, pop = 55, settle = 14, fall = 2, spawn = 28, score_offset = 0;
    int first_link = 0, chain_ready = 0, check = 0;
    json split_costs = json::array();
    std::chrono::steady_clock::time_point deadline;

    void advance(Node& n, int until) const {
        advance_enemy(events, *rates, until, n.event, n.fixed, n.flying,
            n.enemy_fixed, n.enemy_flying, n.enemy_remainder);
        n.frame = until;
    }
    void tick() {
        // The placement count bounds the search, so that the same request gets
        // the same answer; the clock only guards against a stalled machine.
        if (++expanded > max_nodes) throw Exhausted{};
        if (expanded % 64 == 0 && std::chrono::steady_clock::now() >= deadline) throw Exhausted{};
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
                each_remainder_drop(n.field, pending, [&](Field board) { step.due = step.due || board.is_dead(rules); });
        }
        const auto locked = n.field;
        auto masks = n.field.pop();
        step.chain = masks.get_size();
        step.cleared = n.field;
        step.all_clear = step.chain && n.field.is_empty();
        ++n.steps;
        const int gauge_before = n.gauge;
        if (step.chain) {
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
                n.enemy_flying += amount;
                const int duration = geometry ? link_frames(features[i], i == step.chain - 1)
                    : pop + settle + falls[i] * fall;
                advance(n, n.frame + duration - score_offset);
            }
            n.enemy_fixed += n.enemy_flying; n.enemy_flying = 0;
            // Nothing was about to fall: the same offsets stay available later,
            // so a clear made now earns no credit unless it enters Fever.
            if (!step.due && n.gauge < 7) { ++n.early; n.early_gauge += n.gauge - gauge_before; }
            advance(n, n.frame + chain_ready);
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
    // The value of stopping here.
    Outcome leaf(const Node& n) const {
        auto field = n.field;
        if (field.is_dead(rules)) return {false, -1000000000 + i64(n.steps) * 1000, n.gauge};
        const bool entered = n.gauge >= 7;
        const auto stock = fever::stock::evaluate(field, std::max(1, 7 - n.gauge));
        // Links of the longest chain that are gone. A board of single triggers has none to lose.
        const int spent = n.builder_fire ? 0 : std::max(0, root_longest - std::max(1, stock.longest));
        i64 value = i64(n.gauge - root_gauge - (entered ? 0 : n.early_gauge)) * w->gauge
            - i64(n.dropped) * w->drop - i64(n.popped) * w->consume - i64(n.steps) * w->step
            - std::min<i64>(60, n.fixed + n.flying) * w->pending;
        // A main chain spent on a packet it does not clear is gone and the packet is not.
        if (root_longest >= w->mainline_min && n.fixed + n.flying > 0) value -= i64(spent) * w->uncountered;
        if (entered) return {true, value + w->entry, n.gauge};
        u8 heights[6]; field.get_heights(heights);
        value += stock.units * w->stock + stock.colors * w->color
            - i64(spent) * w->mainline
            - i64(std::max(0, int(std::max(heights[2], heights[3])) - 8)) * w->height
            - i64(n.early) * w->early;
        // Nuisance still pending falls on the next placement that pops nothing.
        // A board it would kill is held only by a trigger: the fewer colors
        // fire one with a single puyo, the more it rests on the next piece.
        const int pending = int(std::min<i64>(30, n.fixed + n.flying));
        if (pending) {
            bool stands = true;
            each_remainder_drop(field, pending, [&](Field board) { stands = stands && !board.is_dead(rules); });
            if (!stands) value -= w->exposed * (4 - std::min(3, stock.colors));
        }
        return {true, value, n.gauge};
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
        return depth + 1 >= limit || depth + 1 >= int(pieces.size()) || n.gauge >= 7 ||
            step.all_clear || !step.board_known;
    }
    Outcome below(const Node& n, const Step& step, int depth, int limit) {
        const auto here = leaf(n, step);
        if (!here.alive || ends(n, step, depth, limit)) return here;
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
    search.rules.plain_pairs = true;
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
    root.enemy_fixed = request.contains("enemy_confirmed") ? number(request, "enemy_confirmed", 0, 1000000000) : 0;
    root.enemy_flying = request.contains("enemy_unconfirmed") ? number(request, "enemy_unconfirmed", 0, 1000000000) : 0;
    root.enemy_remainder = request.contains("enemy_remainder") ? number(request, "enemy_remainder", 0, 1000000000) : 0;
    search.root_gauge = root.gauge;
    const auto root_stock = fever::stock::evaluate(field, 7 - root.gauge);
    search.root_longest = root_stock.longest;
    search.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(number(request, "budget_ms", 1, 1000));

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
            first.node.builder_fire = first.step.chain > 0;
        }
        first.here = search.leaf(first.node, first.step);
        firsts.push_back(std::move(first));
    }
    if (firsts.empty()) throw std::invalid_argument("no conservative legal placement");
    std::vector<Outcome> values(firsts.size());
    int completed = 0; bool cutoff = false;
    try {
        for (int limit = 1; limit <= int(search.pieces.size()); ++limit) {
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
    json candidates = json::array();
    size_t best = 0;
    for (size_t i = 0; i < firsts.size(); ++i) {
        const auto& first = firsts[i];
        if (std::make_pair(values[i].alive, values[i].value) > std::make_pair(values[best].alive, values[best].value)) best = i;
        auto shown = first.step.board_known ? first.node.field : first.step.cleared;
        candidates.push_back({{"x", first.move.x}, {"r", std::string(1, fever::text::from_direction(first.move.r))},
            {"chain", first.step.chain}, {"links", first.step.links}, {"link_points", first.step.points},
            {"cancelled", first.step.cancelled}, {"sent", first.step.sent}, {"dropped", first.step.dropped},
            {"drop_due", first.step.due}, {"all_clear", first.step.all_clear},
            {"gauge_after", first.node.gauge}, {"projected_gauge", values[i].gauge},
            {"survives", values[i].alive}, {"value", values[i].value},
            {"post_drop_field_known", first.step.board_known},
            {"possible_drop_boards", first.step.board_known ? 1 : int(first.step.boards.size())},
            {"field", fever::text::from_field(shown)},
            {"confirmed", first.node.fixed}, {"unconfirmed", first.node.flying},
            {"remainder", first.node.remainder}, {"frame", first.node.frame}});
    }
    return {{"choice", candidates[best]}, {"candidates", candidates},
        {"completed_depth", completed}, {"visible", queue.size()}, {"expanded", search.expanded}, {"cutoff", cutoff},
        {"root_stock", {{"units", root_stock.units}, {"links", root_stock.links},
            {"colors", root_stock.colors}, {"longest", root_stock.longest}}},
        {"unknown_drop_policy", "worst_column_choice_then_reobserve"},
        {"future_unconfirmed_arrival", search.events.empty() ? "unscheduled_not_dropped" : "predicted_chain_timeline"}};
}
}

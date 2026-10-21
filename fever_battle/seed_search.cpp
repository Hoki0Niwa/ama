#include "search.h"
#include "../fever/text.h"
#include "physics.h"
#include "timing.h"
#include "disruption.h"
#include "color_needs.h"
#include "rate_schedule.h"
#include "transition.h"
#include "nuisance.h"
#include "../core/fever_queue.h"
#include <chrono>
#include <exception>
#include <algorithm>
#include <array>
#include <map>
#include <cstring>
#include <unordered_map>
#include <memory>
#include <thread>
#include <cmath>
#include <limits>
#include <bit>
#include <tuple>
#include <unordered_set>
#include <functional>

namespace fever_battle {
using json = nlohmann::json;
namespace {
struct Potential { int chain = 0, needed = 4, residue = 78, x = 0; cell::Type color = cell::Type::NONE; };
// One placement of a line, kept as plain data while the search runs. Only the
// line that is returned is written out as JSON: building (and copying) a JSON
// object for every node took most of the time, and a three-piece search was
// cut off by the 50 ms budget before it had seen every line.
struct Step {
    int x = 0; char r = 'U';
    Field field, locked;
    int chain = 0, fire_at = 0, end_at = 0, dropped = 0, phase = 0, drop_cases = 1;
    std::vector<i64> points;
    i64 cancelled = 0, sent = 0, timely_points = 0, total_points = 0;
    bool all_clear = false, dead = false, phase_known = true, field_known = true;
    bool has_all_cases = false, all_cases = true, keeps_ignition = true, completed = false, next_fits = false;
    bool has_extension = false, target_preserved = false;
    int time_reward = 0, remaining_after_rewards = 0;
    i64 carry = 0;      // nuisance left for the normal board if Fever ended after this step
    i64 landed = 0;     // nuisance on the opponent once their observed chain has run out
    EnemyTrays enemy_trays;
    Potential extension;
    i64 extension_points = 0; int extension_frames = 0; double extension_odds = 0;
    i64 worth = 0;      // points expected by the end of the Fever
    double disrupt = 0;
    std::string disruption_kind = "none";
    bool all_cases_preserve() const { return !has_all_cases || all_cases; }
    json describe() {
        json j = {{"x", x}, {"r", std::string(1, r)},
            {"field", fever::text::from_field(field)},
            {"locked_field", fever::text::from_field(locked)},
            {"chain", chain}, {"link_points", points}, {"all_clear", all_clear},
            {"fire_at", fire_at}, {"end_at", end_at}, {"dead", dead}, {"dropped", dropped},
            {"cancelled", cancelled}, {"sent", sent}, {"garbage_phase", phase_known ? json(phase) : json(nullptr)},
            {"post_drop_field_known", field_known}, {"possible_drop_boards", drop_cases},
            {"points_before_timeout", timely_points}, {"total_points", total_points},
            {"completed_before_timeout", completed}, {"next_seed_input_fits", next_fits},
            {"time_reward_frames", time_reward}, {"remaining_after_rewards", remaining_after_rewards},
            {"carried_nuisance", carry}, {"enemy_trays", enemy_trays.json()}, {"enemy_fever_landed", landed}};
        if (has_all_cases) {
            j["all_drop_cases_preserve_target"] = all_cases;
            j["all_drop_cases_keep_ignition"] = keeps_ignition;
        }
        if (has_extension) {
            j["extension_potential"] = {{"chain", extension.chain}, {"needed_cells", extension.needed},
                {"remaining_cells", extension.residue}, {"points", extension_points}, {"chain_frames", extension_frames},
                {"odds", extension_odds}, {"status", "geometric_heuristic_not_visible_solution"}};
            j["target_ignition_preserved"] = target_preserved;
        }
        j["expected_points"] = worth;
        j["projected_disrupt"] = disrupt;
        j["disruption_kind"] = disruption_kind;
        return j;
    }
};
using Rank = std::tuple<int, i64, int, int, int, i64>;
// The placements of a line, the last one first, shared by every line that goes on from them:
// a node holds its state and this, as the normal builder's nodes hold their board and scores.
struct Link {
    Step step;
    std::shared_ptr<const Link> before;
};
using Line = std::shared_ptr<const Link>;
Line extend(const Line& line, Step step) {
    return std::make_shared<const Link>(Link{std::move(step), line});
}
struct SeedNode {
    Field field;
    int frame = 0, confirmed = 0, flying = 0, held_fixed = 0, held_flying = 0, phase = 0;
    i64 remainder = 0;
    EnemyTrays enemy;
    i64 enemy_remainder = 0;
    size_t event_index = 0;
    Line line;          // its placements (none at the root)
    int length = 0;     // placements in the line
    int value = 0;      // of the line so far: which nodes go on to the next piece
    Rank rank;          // of the line if it ended here
    int root = -1;      // the line's first placement, by its index among the root's moves
    double sound = 1;   // odds that the placements that popped nothing left the seed as planned
};
std::vector<Step> steps_of(Line line) {
    std::vector<Step> steps;
    for (; line; line = line->before) steps.push_back(line->step);
    std::reverse(steps.begin(), steps.end());
    return steps;
}
// Geometric evaluation only: these single-color additions are not future
// pieces, executable paths or evidence that the observed seed is solved.
// The chain potential() found, as it resolves: the board it pops from and its links.
struct PotentialFire { Field unpopped; avec<Field, 19> masks; };
// The columns an upright pair can be placed in, as a bit each. Where an upright pair can go does not
// depend on its colour, and move::generate lists its upright placements by column, lowest first.
u8 upright_columns(Field& field, const rule::Rule& rules) {
    const auto probe_color = static_cast<cell::Type>(0);
    auto moves = move::generate(field, piece::from_pair({probe_color, probe_color}), rules);
    u8 columns = 0;
    for (int i = 0; i < moves.get_size(); ++i)
        if (moves[i].r == direction::Type::UP) columns |= u8(1 << moves[i].x);
    return columns;
}
Potential potential(Field field, const rule::Rule& rules, PotentialFire* fire = nullptr, int columns = -1) {
    Potential result;
    if (columns < 0) columns = upright_columns(field, rules);
    for (int c = 0; c < cell::COUNT - 1; ++c) {
        if (field.data[c].is_empty()) continue;
        auto color = static_cast<cell::Type>(c);
        for (int x = 0; x < 6; ++x) {
            if (!(columns & (1 << x))) continue;
            int height = field.get_height(x);
            auto probe = field;
            for (int n = 1; n <= 3 && height + n <= 11; ++n) {
                probe.set_cell(x, height + n - 1, color);
                // The settled board pops nothing: only the group of the added puyos can, and only from four.
                if (probe.data[c].get_mask_group_4(i8(x), i8(height)).get_count() < 4) continue;
                auto resolved = probe;
                auto masks = resolved.pop();
                int chain = masks.get_size();
                if (!chain) continue;
                int residue = resolved.get_count();
                if (std::make_tuple(chain, -residue, -n) >
                    std::make_tuple(result.chain, -result.residue, -result.needed)) {
                    result = {chain, n, residue, x, color};
                    if (fire) *fire = {probe, masks};
                }
                // Additional same-color cells after ignition just inflate a
                // group; they do not describe a nonclearing build sequence.
                break;
            }
        }
    }
    return result;
}
std::vector<i64> points_for(avec<Field, 19>& masks, const std::vector<int>& powers, const Bonuses& bonuses) {
    std::vector<i64> points;
    for (int i = 0; i < masks.get_size(); ++i) {
        if (i >= int(powers.size())) throw std::invalid_argument("missing Fever chain power; no normal fallback");
        points.push_back(score_link(masks[i], powers[i], bonuses).points);
    }
    return points;
}
}

json seed_search(Field field, const json& request) {
    const int width = number(request, "width", 1, 1000);
    // 0: no node limit, as the normal builder's beam (its width and depth bound the search).
    const int max_nodes = number(request, "max_nodes", 0, 100000000);
    // Steam build 15209927's internal Fever timer caps at 1860 frames.
    // The Python protocol validates the caller's explicit clock domain.
    const int remaining = number(request, "remaining_frames", 0, 1860);
    const int maximum = request.contains("maximum_frames") ? number(request, "maximum_frames", 1800, 1860) : 1860;
    const int target = number(request, "seed_chain", 3, 15);
    // Unboosted level behind a normal all-clear entry's first seed (FUN_140050e00); the next level starts from it.
    const int seed_base = request.contains("seed_base") ? number(request, "seed_base", 3, 15) : target;
    const bool unknown_phase = request.value("unknown_garbage_phase", false);
    // Nuisance the stored normal board takes without harm when Fever ends (-1: not given).
    const i64 quiet_limit = request.contains("quiet_carry_limit")
        ? number(request, "quiet_carry_limit", 0, 1000000000) : -1;
    const int safety = number(request, "safety_frames", 0, 600);
    const int rate = number(request, "target_point", 1, 100000);
    const RateSchedule rates(request, rate);
    const auto timing = request.at("timing");
    const int placement = number(timing, "placement_frames", 1, 10000);
    const int spawn = number(timing, "spawn_frames", 0, 10000);
    const int first_link = number(timing, "first_link_frames", 0, 10000);
    const int chain_ready = number(timing, "chain_ready_frames", 0, 10000);
    const int pop_frames = number(timing, "pop_frames", 1, 10000);
    const int settle_frames = number(timing, "settle_frames", 0, 10000);
    const auto split_costs = timing.at("split_extra_frames");
    if (!split_costs.is_array() || split_costs.size() != 14)
        throw std::invalid_argument("split timing must have 14 entries");
    for (const auto& v : split_costs) if (!v.is_number_integer() || v < 0 || v > 10000)
        throw std::invalid_argument("explicit split timing required");
    const auto powers = request.at("powers");
    if (!powers.is_array() || (powers.size() != 17 && powers.size() != 19))
        throw std::invalid_argument("19 Fever powers required (17 from older clients: links 18 and 19 then have no power)");
    for (const auto& v : powers) if (!v.is_number_integer() || v < 0 || v > 999)
        throw std::invalid_argument("invalid Fever power");
    const auto power_table = powers.get<std::vector<int>>();
    const Bonuses bonuses(request.at("bonuses"));
    if (!request.at("count_chain_frames").is_boolean())
        throw std::invalid_argument("explicit chain clock policy required");
    const bool count_chain = request.at("count_chain_frames").get<bool>();
    // One measure ranks every line (see below). The quick and extend strategies it replaced are gone.
    if (request.contains("strategy") && request.at("strategy") != "value")
        throw std::invalid_argument("unknown seed strategy");
    const auto queue = request.at("queue").get<std::vector<std::string>>();
    if (queue.empty() || queue.size() > 3) throw std::invalid_argument("visible queue only");
    std::vector<piece::Piece> pieces;
    for (const auto& text : queue) {
        auto p = fever::text::to_piece(text);
        if (!p) throw std::invalid_argument("invalid piece");
        pieces.push_back(*p);
    }
    // Deeper than the visible pieces, the search reads the same virtual queues as the normal
    // builder (fever::search_multi): the character's cycle gives the shapes, VIRTUAL_COUNT fixed
    // colour bags the colours. Every root placement is ranked by its lines over all of them;
    // what is returned is a visible plan only. Without beam_depth only the visible pieces are read.
    const size_t visible = pieces.size();
    const int depth_limit = request.contains("beam_depth") ? number(request, "beam_depth", int(visible), 64) : int(visible);
    const bool deep = depth_limit > int(visible);
    std::vector<std::vector<piece::Piece>> lines;
    if (deep) {
        const auto* character = dropset::find(request.at("character").get<std::string>());
        if (!character) throw std::invalid_argument("unknown character");
        const u64 index = u64(number(request, "dropset_index", 0, 1000000000));
        for (i32 v = 0; v < fever::VIRTUAL_COUNT; ++v) {
            auto tail = fever::create_queue_virtual(*character, v, usize(depth_limit) - visible, index + visible);
            if (!tail) throw std::invalid_argument("unknown cycle: no virtual pieces");
            auto line = pieces;
            line.insert(line.end(), tail->begin(), tail->end());
            lines.push_back(std::move(line));
        }
    } else lines.push_back(pieces);
    auto rules = rule::FEVER; rules.plain_pairs = true; rules.special_moves = true;
    if (field.is_dead(rules)) throw std::invalid_argument("already dead field");
    SeedNode root; root.field = field;
    root.confirmed = number(request, "confirmed", 0, 1000000000);
    root.flying = number(request, "unconfirmed", 0, 1000000000);
    root.held_fixed = request.contains("held_confirmed") ? number(request, "held_confirmed", 0, 1000000000) : number(request, "held_pending", 0, 1000000000);
    root.held_flying = request.contains("held_unconfirmed") ? number(request, "held_unconfirmed", 0, 1000000000) : 0;
    root.remainder = number(request, "remainder", 0, 1000000000);
    root.phase = number(request, "garbage_phase", 0, 5);
    root.enemy = EnemyTrays(request);
    root.enemy_remainder = request.contains("enemy_remainder") ? number(request, "enemy_remainder", 0, 1000000000) : 0;
    const auto events = request.value("enemy_events", json::array());
    if (!events.is_array()) throw std::invalid_argument("enemy_events must be an array");
    int previous_event = -1;
    for (const auto& event : events) {
        const int at = number(event, "frame", 0, 1000000);
        if (at < previous_event) throw std::invalid_argument("unordered enemy events");
        previous_event = at;
        if (event.at("type") != "end" && event.at("type") != "link")
            throw std::invalid_argument("unknown enemy event");
        if (event.at("type") == "link") number(event, "points", 0, 1000000000);
    }
    const auto advance = [&](SeedNode& state, int until) {
        const auto before = state.event_index;
        advance_enemy(events, rates, until, state.event_index, state.confirmed, state.flying,
            state.enemy, state.enemy_remainder);
        for (auto i = before; i < state.event_index; ++i)
            if (events[i]["type"] == "end") { state.held_fixed += state.held_flying; state.held_flying = 0; }
        state.frame = until;
    };
    auto enemy_baseline = root;
    advance(enemy_baseline, std::numeric_limits<int>::max());
    const i64 enemy_seed_baseline = enemy_baseline.enemy.seed();
    // One measure for every line, the points expected by
    // the end of this Fever. A fire is worth its own points and what the
    // seeds after it can still score on the clock it leaves; a line that pops
    // nothing is worth the chain it has built, by the odds that the puyos it
    // waits for come on the clock that is left. The seeds to come are a template
    // (one colour, four puyos a link), not a forecast of them or of the colours.
    std::vector<i64> template_table{0};
    for (const int power : power_table)
        template_table.push_back(template_table.back() + 40 * std::clamp(
            power + bonuses.group.at(4) + bonuses.color.at(1), bonuses.minimum, bonuses.maximum));
    const auto template_points = [&](int chain) {
        return template_table[std::clamp(chain, 0, int(power_table.size()))];
    };
    // FUN_1400505a0: the all-clear +2 comes before the failure floor.
    const auto next_level = [&](int chain, bool all_clear) {
        return std::clamp(std::max(seed_base - 2, chain + 1 + (all_clear ? 2 : 0)), 3, 15);
    };
    const auto chain_frames = [&](int chain) {
        return first_link + std::max(0, chain - 1) * (pop_frames + settle_frames + 14) + pop_frames;
    };
    // The model's constants come with the request (data/fever/battle_policy.json fever_seed);
    // the defaults are the prototype values they were introduced with.
    const auto model = request.value("value_model", json::object());
    const auto model_number = [&](const char* key, double fallback) {
        if (!model.contains(key)) return fallback;
        const auto& v = model.at(key);
        if (!v.is_number() || v < 0 || v > 1000) throw std::invalid_argument(std::string(key) + " out of range");
        return v.get<double>();
    };
    const double SEED_ODDS = model_number("seed_odds", 0.85);          // a later seed is fired at its level
    const double CARRIED_LEVEL = model_number("carried_level", 0.5);   // the level kept for the next Fever, in its first seed's points
    const double PIECE_ODDS = model_number("piece_odds", 0.5);         // one piece brings a colour that is waited for
    if (PIECE_ODDS <= 0 || PIECE_ODDS > 1) throw std::invalid_argument("piece_odds out of range");
    // A piece takes the model's time or, when the caller has measured its own pieces, that.
    const int piece_frames = std::max(placement + spawn,
        request.contains("pace_frames") ? number(request, "pace_frames", 1, 10000) : 0);
    const int setup_frames = int(piece_frames / PIECE_ODDS);            // the pieces a seed takes to fire, on average
    // Pieces that can still be placed with an ignition before the clock runs out.
    const auto pieces_left = [&](int clock) {
        return std::clamp((clock - first_link - safety - 1) / piece_frames, 0, 60);
    };
    // A piece that pops nothing has to go somewhere: a piece waited through takes this much free board.
    const double WAIT_CELLS = model_number("wait_cells", 3);
    if (WAIT_CELLS < 1) throw std::invalid_argument("wait_cells out of range");
    // Building a seed past its level can go wrong, the sooner the fuller the
    // board: the cube of CROWDED over the free cells is the odds that a
    // placement made for it does, and the seed is lost (6 gives 1 in 8 with
    // twelve cells free, 1 in 80 with twenty-six). On a small seed this hardly weighs;
    // a large one is fired as it stands rather than built on. Keeping a seed
    // for its own level is not charged: there the alternative is to waste it.
    const double CROWDED = model_number("crowded_cells", 6);
    // The seed is built on, towards the next seed's level, by the measure
    // below. The caller names the cases in which it is fired at once instead
    // (`press`): what it sends lands on the opponent's normal board and takes
    // their time to build, or both sides are in Fever and the opponent has
    // nuisance held for their normal board. A fire at the seed's level then
    // ranks above every other line, the earlier the higher, and one that
    // clears the board above those: the all clear is taken wherever it shows.
    const bool press = request.value("press", false);
    const bool enemy_fever = request.value("enemy_fever", false);
    const int their_end = request.contains("their_end") ? number(request, "their_end", 0, 1000000) : -1;
    const int window = request.contains("disrupt_window") ? number(request, "disrupt_window", 0, 100000) : disruption::WINDOW;
    const int enemy_level = request.contains("enemy_seed_level") ? number(request, "enemy_seed_level", 3, 15) : 5;
    const i64 seed_reply = request.contains("enemy_reply_nuisance") ? number(request, "enemy_reply_nuisance", 0, 1000000000) : template_points(enemy_level) / rate;
    const bool skip_jab = request.value("enemy_skip_jab", false);
    const bool current_attack = std::any_of(events.begin(), events.end(), [](const json& e) {
        return e.at("type") == "link" && e.value("points", i64(0)) > 0;
    });
    const auto seed_defense=request.value("enemy_seed_defense",json::array());
    const bool extending=request.value("enemy_extending",false);
    const double PRESSED = 10 * double(template_points(15));
    const auto holds_count = [&](int count) {
        const double share = CROWDED / std::max(1, 72 - count);
        return 1 - std::min(0.9, share * share * share);
    };
    const auto holds = [&](Field& board) { return holds_count(int(board.get_count())); };
    // std::pow(held, k), std::pow(one, needed) and std::pow(1 - one, k) of the waiting lines below, read
    // from tables of the same values: held is 1 or holds() of the board's count, one is PIECE_ODDS / needed.
    constexpr int POWERS = 64;
    std::vector<double> held_power(80 * POWERS), one_power(5 * POWERS), miss_power(5 * POWERS);
    for (int count = 0; count < 80; ++count)
        for (int k = 0; k < POWERS; ++k) held_power[count * POWERS + k] = std::pow(holds_count(count), k);
    for (int needed = 1; needed <= 4; ++needed) {
        const double one = PIECE_ODDS / needed;
        for (int k = 0; k < POWERS; ++k) {
            one_power[needed * POWERS + k] = std::pow(one, k);
            miss_power[needed * POWERS + k] = std::pow(1 - one, k);
        }
    }
    // A seed is not fired for sure because one piece still fits: by the odds
    // that one of the pieces left brings its colour. On a long clock that is
    // close to certain, on the last piece it is PIECE_ODDS.
    double none_brings[61] = {1};
    for (int i = 1; i <= 60; ++i) none_brings[i] = none_brings[i - 1] * (1 - PIECE_ODDS);
    // What the seeds after this one bring: the points they score on the clock,
    // and the level that is left for the next Fever. Only the points offset.
    struct Later { double points, level; };
    const auto later_raw = [&](int level, int clock) {
        double total = 0, kept = 0, odds = 1;
        for (int k = 0; k < 24; ++k) {
            const int pieces = pieces_left(clock);
            if (!pieces) break;
            const double fired = 1 - none_brings[pieces];       // unfired, it stays with its level
            total += odds * fired * template_points(level);
            kept += odds * (1 - fired) * CARRIED_LEVEL * template_points(level);
            odds *= fired * SEED_ODDS;
            clock -= setup_frames + chain_frames(level);
            const int reward = std::max(0, level - 2) * 30;
            level = std::min(15, level + 1);
            if (clock <= 0) break;          // that chain outlasts the clock: it scores, nothing follows
            clock = std::min(maximum, clock + reward) - chain_ready;
        }
        return Later{total, kept + odds * CARRIED_LEVEL * template_points(level)};
    };
    // future() is asked for every line that pops nothing, once for each piece the colour could come with:
    // read from a table of every level and clock instead (the same values).
    std::vector<Later> later_table(16 * 1861);
    for (int level = 3; level <= 15; ++level)
        for (int clock = 1; clock <= 1860; ++clock) later_table[level * 1861 + clock] = later_raw(level, clock);
    const auto future = [&](int level, int clock) {
        return level >= 3 && level <= 15 && clock >= 1 && clock <= 1860 ? later_table[level * 1861 + clock]
            : later_raw(level, clock);
    };
    // Points that offset are worth what they stop, the same as points sent, so
    // nuisance pending is no separate term: more points is less of it. Only
    // what the stored board cannot take at the end weighs beyond that.
    // A nuisance the stored board cannot take, in the points of this many sent
    const double HARMFUL_CARRY = model_number("harmful_carry", 10);
    const auto danger = [&](i64 carry, double points_to_come) {
        const double left = std::max(0.0, double(carry) - points_to_come / rate);
        return std::max(0.0, left - double(std::max<i64>(0, quiet_limit))) * rate * HARMFUL_CARRY;
    };
    // A board that pops nothing is weighed by the chain it holds: where it is fired from, what it scores
    // and how long it runs. That depends on the board alone, and lines that place the same pieces in
    // another order reach the same board: worked out once per board in a search (WaitCache).
    struct Waiting { Potential p; i64 built = 0; int running = 0; };
    // A board as a key: its colour planes and row 14.
    using BoardKey = std::array<u64, 2 * cell::COUNT + 1>;
    static_assert(sizeof(Field::data) == 16 * cell::COUNT);
    struct BoardHash {
        size_t operator()(const BoardKey& key) const {
            u64 h = 0x9E3779B97F4A7C15ull;
            for (const auto word : key) { h ^= word; h *= 0xBF58476D1CE4E5B9ull; h ^= h >> 31; }
            return size_t(h);
        }
    };
    struct WaitCache {
        std::unordered_map<BoardKey, Waiting, BoardHash> boards;
        // A pair's placements depend on the column heights (and whether the board is dead) alone
        // (move::generate: operation::reachable of the heights): its upright columns, by those.
        std::unordered_map<u64, u8> columns;
        i64 hits = 0, misses = 0;
    };
    const auto waiting = [&](Field board, WaitCache& cache) {
        Waiting w;
        PotentialFire fire;
        u8 heights[6];
        board.get_heights(heights);
        u64 shape = u64(board.is_dead(rules));
        for (int x = 0; x < 6; ++x) shape = shape << 8 | heights[x];
        auto known = cache.columns.find(shape);
        if (known == cache.columns.end()) known = cache.columns.emplace(shape, upright_columns(board, rules)).first;
        w.p = potential(board, rules, &fire, known->second);
        if (w.p.chain) {
            // The board with the puyos it waits for, and its links: as potential() resolved them.
            auto& masks = fire.masks;
            int falls[19];
            contact_frames_by_link(fire.unpopped, masks, falls);
            for (int k = 0; k < masks.get_size(); ++k) {
                if (k >= int(power_table.size())) throw std::invalid_argument("missing Fever chain power; no normal fallback");
                w.built += link_points(masks[k], power_table[k], bonuses);
            }
            w.running = first_link;
            for (int k = 0; k < masks.get_size(); ++k)
                w.running += link_frames(falls[k], k == masks.get_size() - 1, pop_frames, settle_frames) +
                    (falls[k] ? 2 : 0);
        }
        return w;
    };
    const auto consider = [&](SeedNode& node, Step& last, int chain, bool alive, int fire_at, int end_at, i64 sent,
                              WaitCache& cache) {
        const bool in_time = (chain ? fire_at : end_at) + safety < remaining;
        const int tier = alive && in_time ? 3 : alive ? 2 : 1;
        const int reward_clear = chain && node.field.is_empty() && in_time ? 1 : 0;
        double worth = 0;
        if (chain) {
            // An in-time ignition scores the whole chain, even if it ends after the clock.
            const int clock = last.completed ? last.remaining_after_rewards - chain_ready : 0;
            const auto later = future(next_level(chain, last.all_clear), clock);
            worth = double(last.total_points) + later.points + later.level - danger(last.carry, later.points);
            // A fire at the seed's level that leaves a packet on a Fever opponent once their chain has
            // run out: waiting for them when their next seed comes it disrupts for sure, otherwise
            // it makes them fire early. Worth half their seed at the first, a quarter at the second.
            if (enemy_fever && chain >= target && in_time && sent > 0) {
                i64 reply_capacity=seed_reply; bool counter_unknown=false;
                if(extending && seed_defense.size()==31) {
                    const auto& counter=seed_defense[std::min<i64>(30,last.landed)];
                    if(counter.value("checked",false) && counter.value("regular_after_drop",false)) {
                        reply_capacity=std::max(reply_capacity,counter.value("reply_nuisance",seed_reply));
                        counter_unknown=!counter.value("counter_complete",false);
                    }
                }
                auto rating = disruption::rate(last.landed, enemy_seed_baseline, reply_capacity,
                    disruption::timed(end_at, their_end, window), true, skip_jab, false, current_attack);
                if(extending && last.landed>enemy_seed_baseline && seed_defense.size()==31) {
                    if(counter_unknown && std::string(rating.kind)!="jab") rating={};
                    const auto& response=seed_defense[std::min<i64>(30,last.landed)];
                    const auto& existing=seed_defense[std::min<i64>(30,enemy_seed_baseline)];
                    const bool already_blocked=enemy_seed_baseline>0 && existing.value("checked",false) && !existing.value("regular_after_drop",false);
                    const auto pressure=disruption::extension(last.landed-enemy_seed_baseline,!already_blocked,
                        response.value("checked",false),response.value("regular_after_drop",false),skip_jab);
                    if(pressure.value>rating.value) rating=pressure;
                }
                last.disrupt = rating.value; last.disruption_kind = rating.kind;
                worth += double(template_points(enemy_level)) * 0.5 * rating.value;
            }
            if (press && chain >= target && in_time)
                worth += PRESSED * (last.all_clear ? 2 : 1) - double(fire_at) * PRESSED / (2.0 * maximum);
        } else {
            // What the chain on the board scores and how long it runs, as a
            // fire is weighed: the chain is known, only its last puyos are not.
            BoardKey key{};
            std::memcpy(key.data(), &node.field.data, sizeof(node.field.data));
            key.back() = node.field.row14;
            auto found = cache.boards.find(key);
            if (found == cache.boards.end()) {
                ++cache.misses;
                found = cache.boards.emplace(std::move(key), waiting(node.field, cache)).first;
            } else ++cache.hits;
            const Potential p = found->second.p;
            const i64 built = found->second.built;
            const int running = found->second.running;
            last.has_extension = true; last.extension = p;
            last.target_preserved = p.chain >= target && last.all_cases_preserve();
            // The puyos come with the first piece, the second, ...: each is a
            // later fire on a shorter clock, for as long as the clock and the
            // free board last. If they never come nothing is fired, and the
            // seed and its level are kept. Several puyos of one colour in one
            // column are each harder to place: a piece brings one of them at
            // PIECE_ODDS / needed.
            const int room = int(std::max(0, 72 - int(node.field.get_count())) / WAIT_CELLS);
            const double held = p.chain > target ? holds(node.field) : 1;
            const int held_row = int(node.field.get_count());
            const auto held_to = [&](int k) {
                return p.chain > target ? (k < POWERS && held_row < 80 ? held_power[held_row * POWERS + k]
                    : std::pow(held, k)) : 1.0;    // held is 1
            };
            const int count = p.chain ? std::min(pieces_left(remaining - end_at), room) : 0;
            const int level = next_level(p.chain, false);
            const double one = PIECE_ODDS / p.needed;
            double odds = 0;
            // Fired with the j-th piece from here, at the odds `now`.
            const auto fires = [&](int j, double now) {
                int clock = remaining - end_at - j * piece_frames - running;
                if (clock > 0) clock = std::min(maximum, clock + std::max(0, p.chain - 2) * 30) - chain_ready;
                const auto later = future(level, clock);
                const double points = double(built) + later.points;
                worth += now * (points + later.level - danger(last.carry, points));
                odds += now;
            };
            // The pieces still visible are known: one that has the puyos fires,
            // one that has not cannot. (A line reaches here with visible pieces
            // left only where a drop ended it.) After them the colours are not
            // known, and a piece brings one puyo at PIECE_ODDS / needed.
            int seen = 0; bool known = false;
            for (size_t k = size_t(node.length); k < pieces.size() && seen < count && !known; ++k) {
                ++seen;
                int have = 0;
                if (pieces[k].shape == piece::Shape::BIG) have = p.needed <= 2 ? p.needed : 0;
                else for (const auto color : pieces[k].colors) have += color == p.color;
                if (have >= p.needed) { fires(seen, held_to(seen - 1)); known = true; }
            }
            if (!known) {
                double ways = 1;
                for (int j = p.needed; j <= count - seen; ++j) {
                    const bool tabled = p.needed >= 1 && p.needed <= 4 && j - p.needed < POWERS;
                    const double now = ways * (tabled ? one_power[p.needed * POWERS + p.needed] : std::pow(one, p.needed)) *
                        (tabled ? miss_power[p.needed * POWERS + j - p.needed] : std::pow(1 - one, j - p.needed)) *
                        held_to(seen + j - 1);
                    ways = ways * j / (j - p.needed + 1);
                    fires(seen + j, now);
                }
            }
            // The puyos never come: the seed is kept unfired with its level, or
            // given up on the next piece for the seed two levels down, whichever
            // is worth more. Any small pop gives it up, so a line that waits is
            // never worth less than failing one piece later; what has dropped
            // on this board meanwhile leaves with it.
            const double miss = CARRIED_LEVEL * template_points(target) - danger(last.carry, 0);
            double given_up = miss;
            {
                int clock = remaining - end_at - piece_frames - chain_frames(1);
                if (clock > 0) {
                    const auto later = future(next_level(1, false), clock - chain_ready);
                    given_up = later.points + later.level - danger(last.carry, later.points);
                }
            }
            worth += (1 - odds) * std::max(miss, given_up);
            last.extension_points = built; last.extension_frames = running; last.extension_odds = odds;
        }
        if (node.sound < 1 && (chain ? chain : last.extension.chain) > target) {
            // The placements before this did not hold: the seed is spent for nothing.
            const double lost = CARRIED_LEVEL * template_points(next_level(1, false)) - danger(last.carry, 0);
            worth = node.sound * worth + (1 - node.sound) * lost;
        }
        const i64 value = i64(worth);
        node.value = int(std::clamp<i64>(value, -2000000000, 2000000000));
        last.worth = value;
        node.rank = std::make_tuple(tier, value, reward_clear, chain, -end_at, sent);
    };
    // A line is ranked where it ends: at a fire, or where the visible pieces
    // end. A placement that pops nothing and is followed by a visible piece is
    // worth its best continuation, not the puyos it could wait for: the pieces
    // that follow are known.
    // What every child reads, out of the request once.
    int split_frames[14];
    for (int k = 0; k < 14; ++k) split_frames[k] = split_costs[k].get<int>();
    const int nuisance_check = timing.value("nuisance_check_frames", 0);
    const int nuisance_ready = timing.value("nuisance_ready_frames", 0);
    // The state that tells the nodes of a layer apart (transition.h state_key, as fixed data: the whole
    // Field and the same numbers).
    struct StateKey {
        std::array<char, sizeof(Field)> field;
        std::array<i64, 14> numbers;
        bool operator==(const StateKey& other) const {
            return field == other.field && numbers == other.numbers;
        }
    };
    struct StateHash {
        size_t operator()(const StateKey& key) const {
            u64 h = 0x9E3779B97F4A7C15ull;
            const auto mix = [&](u64 word) { h ^= word; h *= 0xBF58476D1CE4E5B9ull; h ^= h >> 31; };
            for (size_t k = 0; k + 8 <= key.field.size(); k += 8) {
                u64 word; std::memcpy(&word, key.field.data() + k, 8); mix(word);
            }
            for (const auto number : key.numbers) mix(u64(number));
            return size_t(h);
        }
    };
    const auto state_of = [](const SeedNode& n) {
        StateKey key;
        std::memcpy(key.field.data(), &n.field, sizeof(Field));
        key.numbers = {i64(n.frame), i64(n.confirmed), i64(n.flying), i64(n.held_fixed), i64(n.held_flying),
            i64(n.remainder), i64(n.phase), i64(n.event_index), i64(n.enemy.normal_fixed), i64(n.enemy.normal_flying),
            i64(n.enemy.fever_fixed), i64(n.enemy.fever_flying), i64(n.enemy.fever), i64(n.enemy_remainder)};
        return key;
    };
    // One search over one queue: the visible pieces, or them and one virtual queue.
    struct Run {
        Line best_path;
        Rank best_rank{-1, 0, 0, 0, 0, 0};
        int expanded = 0; bool cutoff = false;
        Rank kind_rank[3];
        Line kind_path[3];
        bool root_complete = false, root_build_preserves_target = false;
        std::map<int, std::pair<Rank, Line>> roots;    // the best line of each root placement
        i64 cache_hits = 0, cache_misses = 0;
    };
    const auto run = [&](const std::vector<piece::Piece>& pieces) {
    Run out;
    auto& best_path = out.best_path; auto& best_rank = out.best_rank;
    auto& expanded = out.expanded; auto& cutoff = out.cutoff;
    auto& kind_rank = out.kind_rank; auto& kind_path = out.kind_path;
    auto& root_complete = out.root_complete; auto& root_build_preserves_target = out.root_build_preserves_target;
    std::vector<SeedNode> layer{root};
    WaitCache cache;
    // A line that ends: a layer node (last null: its line is complete), or a child with its last placement.
    const auto offer = [&](const SeedNode& node, const Step* last) {
        Line line = last ? Line() : node.line;
        const auto line_once = [&] { if (!line) line = extend(node.line, *last); return line; };
        if (node.rank > best_rank) { best_rank = node.rank; best_path = line_once(); }
        const int chain = last ? last->chain : node.line->step.chain;
        const int kind = !chain ? 2 : chain >= target ? 0 : 1;
        if (!kind_path[kind] || node.rank > kind_rank[kind]) {
            kind_rank[kind] = node.rank; kind_path[kind] = line_once();
        }
        auto found = out.roots.find(node.root);
        if (found == out.roots.end()) out.roots.emplace(node.root, std::make_pair(node.rank, line_once()));
        else if (node.rank > found->second.first) found->second = {node.rank, line_once()};
    };
    for (size_t depth = 0; depth < pieces.size() && !layer.empty() && !cutoff; ++depth) {
        // The children that go on, each with the record of its placement until the layer is chosen.
        struct Child { SeedNode node; Step step; };
        std::vector<Child> next;
        size_t done = 0;        // parents whose every placement was tried
        for (auto& parent : layer) {
            bool continued = false;
            auto moves = move::generate(parent.field, pieces[depth], rules);
            for (int i = 0; i < moves.get_size(); ++i) {
                if (depth == 0 && request.contains("allowed")) {
                    bool allowed = false;
                    for (const auto& m : request.at("allowed"))
                        allowed |= m.at("x") == moves[i].x && m.at("r") ==
                            std::string(1, fever::text::from_direction(moves[i].r));
                    if (!allowed) continue;
                }
                // Always establish an executable root fallback before honoring
                // node cutoffs. Node termination returns a complete JSON.
                if ((best_path || depth > 0 || !next.empty()) &&
                    max_nodes && expanded >= max_nodes) {
                    cutoff = true; break;
                }
                ++expanded;
                SeedNode child = parent;
                if (depth == 0) child.root = i;
                auto splits = split_distances(child.field, pieces[depth], moves[i].x, moves[i].r);
                int split = *std::max_element(splits.begin(), splits.end());
                advance(child, child.frame + placement + split_frames[split]);
                if (!child.field.drop_piece(moves[i].x, moves[i].r, pieces[depth], rules)) continue;
                auto locked = child.field;
                auto masks = child.field.pop();
                const auto falls = contact_frames_by_link(locked, masks);
                auto points = points_for(masks, power_table, bonuses);
                const int chain = masks.get_size();
                int fire_at = child.frame + (chain ? first_link : 0);
                int end_at = fire_at;
                i64 sent = 0, cancelled = 0, timely_points = 0;
                for (int k = 0; k < chain; ++k) {
                    advance(child, end_at);
                    if ((!count_chain ? fire_at : end_at) + safety < remaining)
                        timely_points += points[k];
                    i64 total = points[k] + child.remainder;
                    const int active_rate = rates.at(end_at);
                    i64 amount = total / active_rate; child.remainder = total % active_rate;
                    if (i64(child.confirmed) + child.flying + child.held_fixed + child.held_flying && amount == 0) amount = 1;
                    for (int* pending : {&child.confirmed, &child.flying, &child.held_fixed, &child.held_flying}) {
                        int n = int(std::min<i64>(*pending, amount));
                        *pending -= n; amount -= n; cancelled += n;
                    }
                    sent += amount;
                    child.enemy.send(amount, end_at);
                    end_at += link_frames(falls[k], k == chain - 1, pop_frames, settle_frames);
                }
                if (chain) child.enemy.confirm();
                int dropped = 0, drop_cases = 1;
                bool drop_alive = true, drop_target_preserved = true, drop_keeps_ignition = true;
                std::vector<Field> drop_boards;
                auto observed_result = child.field;
                if (!chain) {
                    advance(child, child.frame + nuisance_check);
                    dropped = std::min(30, child.confirmed); child.confirmed -= dropped;
                    if (unknown_phase && dropped % 6) {
                        // Every remainder subset must preserve both survival
                        // and a reachable ignition. The guessed board is not
                        // returned; one move is, and the drop is observed.
                        drop_cases = 0;
                        // The board the line is weighed on: the worst the unknown columns can leave.
                        std::tuple<int,int,int,int> worst{100, 0, 0, 0};
                        each_remainder_drop(observed_result, dropped, [&](Field outcome) {
                            ++drop_cases;
                            bool survives = !outcome.is_dead(rules);
                            drop_alive &= survives;
                            drop_boards.push_back(outcome);
                            auto p = potential(outcome, rules);
                            drop_target_preserved &= p.chain >= target;
                            drop_keeps_ignition &= p.chain > 0;
                            auto rank = std::make_tuple(int(survives), p.chain, -p.needed, -p.residue);
                            if (rank < worst) { worst = rank; child.field = outcome; }
                        });
                    } else {
                        drop_nuisance(child.field, dropped, child.phase);
                        if (dropped) {
                            drop_boards.push_back(child.field);
                            drop_target_preserved = potential(child.field, rules).chain >= target;
                        }
                    }
                    child.phase = (child.phase + dropped) % 6;
                    end_at = child.frame;
                }
                const bool field_known = !unknown_phase || dropped % 6 == 0;
                bool alive = drop_alive && !child.field.is_dead(rules);
                Step step;
                step.x = moves[i].x; step.r = fever::text::from_direction(moves[i].r);
                step.field = field_known ? child.field : observed_result; step.locked = locked;
                step.chain = chain; step.all_clear = child.field.is_empty();
                step.fire_at = fire_at; step.end_at = end_at; step.dead = !alive; step.dropped = dropped;
                step.cancelled = cancelled; step.sent = sent;
                step.phase_known = !unknown_phase; step.phase = child.phase;
                step.field_known = field_known; step.drop_cases = drop_cases;
                step.keeps_ignition = drop_keeps_ignition;
                if (unknown_phase && dropped % 6) { step.has_all_cases = true; step.all_cases = drop_target_preserved; }
                step.timely_points = timely_points;
                for (const auto point : points) step.total_points += point;
                int error = 0;
                for (const int fall : falls) if (fall) error += 2;
                const int clock_end = count_chain ? end_at + error : fire_at;
                step.completed = chain && clock_end + safety < remaining;
                int after_end = std::max(0, remaining - clock_end);
                step.time_reward = step.completed ? std::min(maximum-after_end, std::max(0, chain - 2) * 30) : 0;
                after_end += step.time_reward;
                // Full-clear time is awarded at a separate boundary 16F later.
                if (step.completed && step.all_clear && after_end > 16 + safety) {
                    after_end -= 16;
                    const int award = std::min(300, maximum-after_end);
                    step.time_reward += award;
                    after_end += award;
                } else if (step.all_clear) after_end = std::max(0, after_end - 16);
                step.remaining_after_rewards = after_end;
                step.next_fits = step.completed && after_end >
                    chain_ready - (step.all_clear ? 16 : 0) + placement + first_link + safety;
                step.points = std::move(points);
                // What the observed enemy chain has yet to score arrives whatever
                // this line does. Every line is charged with all of it: counted
                // only up to the line's own end, a long chain would look worse
                // than a short one for having watched more of it land.
                auto ahead_index = child.event_index;
                int ahead_fixed = child.confirmed, ahead_flying = child.flying;
                auto their_trays = child.enemy; i64 their_remainder = child.enemy_remainder;
                advance_enemy(events, rates, std::numeric_limits<int>::max(), ahead_index, ahead_fixed, ahead_flying,
                    their_trays, their_remainder);
                // A drop taken on the Fever board leaves with it; one that locks
                // after the clock has run out is not counted as taken.
                step.landed = their_trays.seed();
                step.enemy_trays = their_trays;
                step.carry = i64(child.held_fixed) + child.held_flying + ahead_fixed + ahead_flying +
                    (dropped && end_at + safety >= remaining ? dropped : 0);
                child.length = parent.length + 1;
                if (!chain) child.sound *= holds(parent.field);
                consider(child, step, chain, alive, fire_at, end_at, sent, cache);
                continued = true;
                if (depth == 0 && alive && !chain)
                    root_build_preserves_target |= step.extension.chain >= target && step.all_cases_preserve();
                // The line goes on to the next visible piece across a drop as well:
                // what the pieces in sight then do is read, not estimated. On
                // unknown columns it is read on the worst board they can leave
                // (chosen above). That board weighs the line and is never
                // returned: the caller places one piece and observes the drop.
                const int ready = dropped ? nuisance_ready : std::max(0, spawn - nuisance_check);
                if (depth + 1 < pieces.size() && alive && !chain &&
                    end_at + ready + safety < remaining) {
                    advance(child, end_at + ready);
                    next.push_back({std::move(child), std::move(step)});
                } else offer(child, &step);
            }
            if (cutoff) break;
            if (depth > 0 && !continued) offer(parent, nullptr);     // no placement of the next piece: it ends here
            ++done;
        }
        if (cutoff) {
            // The search stops here: what was not followed is ranked as it stands.
            for (size_t i = done; depth > 0 && i < layer.size(); ++i) offer(layer[i], nullptr);
            for (const auto& one : next) offer(one.node, &one.step);
        }
        if (depth == 0 && !cutoff) root_complete = true;
        // Preserve distinct boards and garbage state at each visible position: the children in order of
        // value, then the earlier, then as they came (sorted by index), the first of each state kept.
        std::vector<int> order(next.size());
        for (size_t k = 0; k < order.size(); ++k) order[k] = int(k);
        std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
            return std::make_tuple(next[a].node.value, -next[a].node.frame) >
                std::make_tuple(next[b].node.value, -next[b].node.frame);
        });
        std::unordered_set<StateKey, StateHash> seen; layer.clear();
        for (const int k : order) {
            auto& n = next[k].node;
            if (seen.insert(state_of(n)).second) {
                n.line = extend(n.line, std::move(next[k].step));
                layer.push_back(std::move(n));
            }
            if (layer.size() >= size_t(width)) break;
        }
    }
    out.cache_hits = cache.hits; out.cache_misses = cache.misses;
    return out;
    };
    std::vector<Run> runs(lines.size());
    if (runs.size() == 1) runs[0] = run(lines[0]);
    else {
        std::vector<std::exception_ptr> errors(runs.size());
        std::vector<std::thread> threads;
        for (size_t v = 0; v < runs.size(); ++v)
            threads.emplace_back([&, v] {
                try { runs[v] = run(lines[v]); } catch (...) { errors[v] = std::current_exception(); }
            });
        for (auto& t : threads) t.join();
        for (const auto& e : errors) if (e) std::rethrow_exception(e);
    }
    const Run& first = runs[0];
    const auto& kind_rank = first.kind_rank;
    std::vector<Step> kind_path[3];
    for (int k = 0; k < 3; ++k) kind_path[k] = steps_of(first.kind_path[k]);
    const bool root_complete = first.root_complete, root_build_preserves_target = first.root_build_preserves_target;
    int expanded = 0; bool cutoff = false;
    i64 cache_hits = 0, cache_misses = 0;
    for (const auto& one : runs) {
        expanded += one.expanded; cutoff |= one.cutoff;
        cache_hits += one.cache_hits; cache_misses += one.cache_misses;
    }
    std::vector<Step> best_path = steps_of(first.best_path);
    json virtual_values = json::array();
    i64 expected = 0;
    bool truncated = false;
    if (deep) {
        // A root placement is ranked by its worst tier over the queues, then by its points summed
        // over them (as search_multi sums each candidate's chain score). Its line is the first queue's.
        std::tuple<int, i64, int> chosen{-1, 0, 0};
        int chosen_root = -1;
        for (const auto& [r, entry] : first.roots) {
            int tier = 3, clears = 0; i64 sum = 0; bool everywhere = true;
            for (const auto& one : runs) {
                const auto found = one.roots.find(r);
                if (found == one.roots.end()) { everywhere = false; break; }
                tier = std::min(tier, std::get<0>(found->second.first));
                sum += std::get<1>(found->second.first);
                clears += std::get<2>(found->second.first);
            }
            if (!everywhere) continue;
            const auto key = std::make_tuple(tier, sum, clears);
            if (chosen_root < 0 || key > chosen) { chosen = key; chosen_root = r; }
        }
        if (chosen_root >= 0) {
            best_path = steps_of(first.roots.at(chosen_root).second);
            for (const auto& one : runs) virtual_values.push_back(std::get<1>(one.roots.at(chosen_root).first));
            expected = std::get<1>(chosen) / i64(runs.size());
        }
        if (best_path.size() > visible) { best_path.resize(visible); truncated = true; }
    }
    if (best_path.empty()) throw std::invalid_argument("no conservative legal placement");
    // The line ranked first stands: nothing is swapped in after the search.
    const auto& last = best_path.back();
    bool on_known_boards = true;
    for (size_t k = 0; k + 1 < best_path.size(); ++k) on_known_boards &= best_path[k].field_known;
    const bool solved = on_known_boards && !last.dead && last.chain >= target && last.fire_at + safety < remaining;
    const bool deadline_failure = (root.held_fixed + root.held_flying) && count_chain && !best_path[0].dead &&
        best_path[0].chain > 0 && best_path[0].chain < target &&
        best_path[0].end_at >= remaining + safety;
    const bool emergency_failure = root_complete && root.confirmed > 0 && !root_build_preserves_target &&
        !best_path[0].dead && best_path[0].chain > 0 && best_path[0].chain < target;
    const bool intentional_failure = deadline_failure || emergency_failure;
    // What was read past a drop on unknown columns weighed the line; it is not
    // a plan. The path returned ends at that drop, with the line's value.
    json line = json::array();
    bool guessed = false;
    for (auto& step : best_path) {
        line.push_back(step.describe());
        if (!step.field_known && &step != &best_path.back()) { guessed = true; break; }
    }
    if (guessed) line.back()["expected_points"] = best_path.back().worth;
    if (deep) line.back()["expected_points"] = expected;
    // The best line of each kind, to read why the chosen one was ranked first.
    json alternatives = json::object();
    const char* kinds[3] = {"regular_fire", "short_fire", "no_pop"};
    for (int k = 0; k < 3; ++k) if (!kind_path[k].empty()) {
        const auto& steps = kind_path[k];
        alternatives[kinds[k]] = {{"x", steps[0].x}, {"r", std::string(1, steps[0].r)},
            {"placements", steps.size()}, {"chain", steps.back().chain},
            {"in_time", std::get<0>(kind_rank[k]) == 3}, {"expected_points", steps.back().worth}};
        if (k == 2) alternatives[kinds[k]]["extension_chain"] = steps.back().extension.chain;
    }
    return {{"choice", line[0]}, {"path", line}, {"solved", solved}, {"alternatives", alternatives},
        {"target_chain", target}, {"expanded", expanded}, {"cutoff", cutoff},
        {"waiting_boards", {{"evaluated", cache_misses}, {"reused", cache_hits}}},
        {"requires_new_seed_after_clear", best_path.back().chain > 0},
        {"new_seed_spawn_possible", last.chain > 0 && (count_chain ? last.end_at < remaining+safety : last.fire_at < remaining)},
        {"requires_reobservation_after_drop", best_path.back().dropped > 0},
        {"searched_visible", queue.size()}, {"beam_depth", depth_limit},
        {"virtual_count", deep ? lines.size() : 0}, {"virtual_values", virtual_values},
        {"virtual_line_truncated", truncated}, {"press", press}, {"pending_arrival_status", events.empty() ? "unconfirmed_not_scheduled" : "observed_enemy_chain_timeline"},
        {"strategy", "value"},
        {"seed_color_needs", color_needs(field).describe(pieces, 0)},
        {"intentional_seed_failure", intentional_failure},
        {"failure_avoidance_status", deadline_failure ? "final_piece_chain_outlasts_clock" :
            emergency_failure ? "confirmed_drop_blocks_required_ignition" : "not_proven_required"},
        {"remaining_piece_budget", {{"includes_current", true},
            {"minimum_estimate", 1 + std::max(0,remaining-safety-1)/(placement+spawn+split_costs[13].get<int>())},
            {"maximum_estimate", 1 + std::max(0,remaining-safety-1)/(placement+spawn)},
            {"status", "estimated_spawn_counts_split_range_not_ignition_probability"}}},
        {"objective", "expected_points_by_the_end_of_this_fever"},
        {"clock_policy", count_chain ? "counts_chain" : "stops_during_chain"}};
}
}

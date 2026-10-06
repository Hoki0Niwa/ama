#include "search.h"
#include "../fever/text.h"
#include "physics.h"
#include "timing.h"
#include "color_needs.h"
#include <chrono>
#include <bit>
#include <tuple>
#include <unordered_set>

namespace fever_battle {
using json = nlohmann::json;
namespace {
int number(const json& j, const char* key, int low, int high) {
    const auto& v = j.at(key);
    if (!v.is_number_integer() || v < low || v > high)
        throw std::invalid_argument(std::string(key) + " out of range");
    return v.get<int>();
}
struct Potential { int chain = 0, needed = 4, residue = 78; };
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
    bool has_all_cases = false, all_cases = true, completed = false, next_fits = false;
    bool has_extension = false, target_preserved = false;
    Potential extension; int setup_bonus = 0;
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
            {"completed_before_timeout", completed}, {"next_seed_input_fits", next_fits}};
        if (has_all_cases) j["all_drop_cases_preserve_target"] = all_cases;
        if (has_extension) {
            j["extension_potential"] = {{"chain", extension.chain}, {"needed_cells", extension.needed},
                {"remaining_cells", extension.residue}, {"status", "geometric_heuristic_not_visible_solution"}};
            j["target_ignition_preserved"] = target_preserved;
            j["all_clear_setup_bonus"] = setup_bonus;
        }
        return j;
    }
};
struct SeedNode {
    Field field;
    int frame = 0, confirmed = 0, flying = 0, held = 0, phase = 0;
    i64 remainder = 0;
    std::vector<Step> path;
    int build_value = 0;
};
// Geometric evaluation only: these single-color additions are not future
// pieces, executable paths or evidence that the observed seed is solved.
Potential potential(Field field, const rule::Rule& rules) {
    Potential result;
    // Where an upright pair can go does not depend on its colour: generated once.
    const auto probe_color = static_cast<cell::Type>(0);
    auto moves = move::generate(field, piece::from_pair({probe_color, probe_color}), rules);
    for (int c = 0; c < cell::COUNT - 1; ++c) {
        if (field.data[c].is_empty()) continue;
        auto color = static_cast<cell::Type>(c);
        for (int i = 0; i < moves.get_size(); ++i) {
            if (moves[i].r != direction::Type::UP) continue;
            int x = moves[i].x, height = field.get_height(x);
            auto probe = field;
            for (int n = 1; n <= 3 && height + n <= 11; ++n) {
                probe.set_cell(x, height + n - 1, color);
                auto resolved = probe;
                int chain = resolved.pop_count();
                if (!chain) continue;
                int residue = resolved.get_count();
                if (std::make_tuple(chain, -residue, -n) >
                    std::make_tuple(result.chain, -result.residue, -result.needed))
                    result = {chain, n, residue};
                // Additional same-color cells after ignition just inflate a
                // group; they do not describe a nonclearing build sequence.
                break;
            }
        }
    }
    return result;
}
void drop_nuisance(Field& field, int count, int phase) {
    constexpr int order[] = {0, 3, 2, 5, 1, 4};
    u8 heights[6]; field.get_heights(heights);
    int amounts[6]; for (auto& n : amounts) n = count / 6;
    for (int i = 0; i < count % 6; ++i) ++amounts[order[(phase + i) % 6]];
    for (int x = 0; x < 6; ++x) for (int i = 0; i < amounts[x]; ++i)
        if (heights[x] < 13) field.set_cell(x, heights[x]++, cell::Type::GARBAGE);
}
std::vector<i64> points_for(avec<Field, 19>& masks, const json& powers, const json& bonuses) {
    std::vector<i64> points;
    for (int i = 0; i < masks.get_size(); ++i) {
        if (i >= int(powers.size())) throw std::invalid_argument("missing Fever chain power; no normal fallback");
        auto mask = masks[i]; int colors = 0, count = 0, bonus = 0;
        for (int c = 0; c < cell::COUNT - 1; ++c) {
            if (mask.data[c].is_empty()) continue;
            ++colors;
            while (!mask.data[c].is_empty()) {
                auto group = mask.data[c].get_mask_group_lsb();
                int n = group.get_count(); count += n;
                bonus += bonuses.at("group").at(std::min(11, n)).get<int>();
                mask.data[c] = mask.data[c] & ~group;
            }
        }
        int multiplier = std::clamp(powers.at(i).get<int>() + bonus + bonuses.at("color").at(colors).get<int>(),
            bonuses.at("multiplier_min").get<int>(), bonuses.at("multiplier_max").get<int>());
        points.push_back(10 * count * multiplier);
    }
    return points;
}
}

json seed_search(Field field, const json& request) {
    const int width = number(request, "width", 1, 1000);
    const int max_nodes = number(request, "max_nodes", 1, 100000);
    const int budget_ms = number(request, "budget_ms", 1, 1000);
    // Steam build 15209927's internal Fever timer caps at 1860 frames.
    // The Python protocol validates the caller's explicit clock domain.
    const int remaining = number(request, "remaining_frames", 0, 1860);
    const int target = number(request, "seed_chain", 3, 15);
    const int extension_moves = request.contains("extension_moves")
        ? number(request, "extension_moves", 0, 1000000000) : 0;
    const int patience = std::max(0, 15 - target);
    const int gain = target <= 5 ? 3 : target <= 8 ? 2 : target <= 12 ? 1 : 0;
    const bool unknown_phase = request.value("unknown_garbage_phase", false);
    const int safety = number(request, "safety_frames", 0, 600);
    const int rate = number(request, "target_point", 1, 100000);
    const auto timing = request.at("timing");
    const int placement = number(timing, "placement_frames", 1, 10000);
    const int spawn = number(timing, "spawn_frames", 0, 10000);
    const auto split_costs = timing.at("split_extra_frames");
    if (!split_costs.is_array() || split_costs.size() != 14)
        throw std::invalid_argument("split timing must have 14 entries");
    for (const auto& v : split_costs) if (!v.is_number_integer() || v < 0 || v > 10000)
        throw std::invalid_argument("explicit split timing required");
    const auto powers = request.at("powers"), bonuses = request.at("bonuses");
    if (!powers.is_array() || powers.size() != 17)
        throw std::invalid_argument("17 Fever powers required");
    for (const auto& v : powers) if (!v.is_number_integer() || v < 0 || v > 999)
        throw std::invalid_argument("invalid Fever power");
    if (!request.at("count_chain_frames").is_boolean())
        throw std::invalid_argument("explicit chain clock policy required");
    const bool count_chain = request.at("count_chain_frames").get<bool>();
    const auto strategy = request.at("strategy").get<std::string>();
    if (strategy != "quick" && strategy != "extend") throw std::invalid_argument("unknown seed strategy");
    const auto queue = request.at("queue").get<std::vector<std::string>>();
    if (queue.empty() || queue.size() > 3) throw std::invalid_argument("visible queue only");
    std::vector<piece::Piece> pieces;
    for (const auto& text : queue) {
        auto p = fever::text::to_piece(text);
        if (!p) throw std::invalid_argument("invalid piece");
        pieces.push_back(*p);
    }
    auto rules = rule::FEVER; rules.plain_pairs = true;
    if (field.is_dead(rules)) throw std::invalid_argument("already dead field");
    SeedNode root; root.field = field;
    root.confirmed = number(request, "confirmed", 0, 1000000000);
    root.flying = number(request, "unconfirmed", 0, 1000000000);
    root.held = number(request, "held_pending", 0, 1000000000);
    root.remainder = number(request, "remainder", 0, 1000000000);
    root.phase = number(request, "garbage_phase", 0, 5);
    const auto start = std::chrono::steady_clock::now();
    std::vector<SeedNode> layer{root};
    std::vector<Step> best_path;
    std::tuple<int, i64, int, int, int, i64> best_rank{-1, 0, 0, 0, 0, 0};
    int expanded = 0; bool cutoff = false;
    bool root_complete = false, root_build_preserves_target = false;
    const auto build_value = [&](Field board, const Potential& p, int steps, int end_at) {
        u8 heights[6]; board.get_heights(heights);
        int risk = 0; for (auto h : heights) risk += std::max(0, int(h) - 8) * 180;
        const bool can_wait = extension_moves + steps <= patience &&
            end_at + spawn + placement + 15 + safety < remaining &&
            std::max(heights[2], heights[3]) < 10;
        return can_wait && p.chain >= target
            ? p.chain * 1000 + (15 - target) * 100
                - p.needed * 90 - steps * 100 - risk
                + (p.residue <= 4 ? 700 - p.residue * 100 : 0)
            : -100000 - risk;
    };
    const auto consider = [&](SeedNode& node, int chain, bool alive, int fire_at, int end_at, i64 sent) {
        const bool in_time = (chain ? fire_at : end_at) + safety < remaining;
        const bool completed = (count_chain ? end_at : fire_at) + safety < remaining;
        const bool success = chain >= target && in_time && alive;
        int tier = alive && in_time ? 3 : alive ? 2 : 1;
        const int reward_clear = chain && node.field.is_empty() && in_time ? 1 : 0;
        i64 value = 0;
        if (chain) {
            value = chain * 1000 + reward_clear * 3000;
            if (chain < target) value -= (target - chain) * 1200;
            if (chain <= 2 && !reward_clear) value -= 1500;
            if (chain >= target + gain) value += 1500;
        } else if (strategy == "extend") {
            auto p = potential(node.field, rules);
            value = build_value(node.field, p, int(node.path.size()), end_at);
            node.build_value = int(value);
            auto& step = node.path.back();
            step.has_extension = true; step.extension = p;
            step.target_preserved = p.chain >= target && step.all_cases_preserve();
            step.setup_bonus = p.residue <= 4 ? 700 - p.residue * 100 : 0;
        } else {
            node.build_value = -int(node.field.get_height_max());
        }
        // An in-time ignition scores the WHOLE chain, even if it ends after
        // timeout. Completion/next-seed time is a distinct secondary objective.
        const i64 total_points = chain ? node.path.back().total_points : 0;
        const bool next_seed_fits = completed &&
            (count_chain ? end_at : fire_at) + spawn + placement + 15 + safety < remaining;
        auto rank = strategy == "quick"
            ? std::make_tuple(tier, total_points + reward_clear * i64(rate) * 30,
                int(success && next_seed_fits), reward_clear, -end_at, sent)
            : std::make_tuple(tier, value, reward_clear, chain, -end_at, sent);
        if (rank > best_rank) { best_rank = rank; best_path = node.path; }
    };
    for (size_t depth = 0; depth < pieces.size() && !layer.empty() && !cutoff; ++depth) {
        std::vector<SeedNode> next;
        for (auto& parent : layer) {
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
                // CPU/node cutoffs. Budget termination returns a complete JSON.
                const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::steady_clock::now() - start).count();
                if (!best_path.empty() && (expanded >= max_nodes || elapsed >= budget_ms)) {
                    cutoff = true; break;
                }
                ++expanded;
                SeedNode child = parent;
                auto splits = split_distances(child.field, pieces[depth], moves[i].x, moves[i].r);
                int split = *std::max_element(splits.begin(), splits.end());
                child.frame += placement + split_costs[split].get<int>();
                if (!child.field.drop_piece(moves[i].x, moves[i].r, pieces[depth], rules)) continue;
                auto locked = child.field;
                auto masks = child.field.pop();
                auto features = fall_features(locked, masks);
                auto points = points_for(masks, powers, bonuses);
                const int chain = masks.get_size();
                int fire_at = child.frame + (chain ? 15 : 0);
                int end_at = fire_at;
                i64 sent = 0, cancelled = 0, timely_points = 0;
                for (int k = 0; k < chain; ++k) {
                    if ((!count_chain ? fire_at : end_at) + safety < remaining)
                        timely_points += points[k];
                    i64 total = points[k] + child.remainder;
                    i64 amount = total / rate; child.remainder = total % rate;
                    if (i64(child.confirmed) + child.flying + child.held && amount == 0) amount = 1;
                    for (int* pending : {&child.confirmed, &child.flying, &child.held}) {
                        int n = int(std::min<i64>(*pending, amount));
                        *pending -= n; amount -= n; cancelled += n;
                    }
                    sent += amount;
                    end_at += link_frames(features[k], k == chain - 1);
                }
                int dropped = 0, drop_cases = 1;
                bool drop_alive = true, drop_target_preserved = true;
                auto observed_result = child.field;
                if (!chain) {
                    dropped = std::min(30, child.confirmed); child.confirmed -= dropped;
                    if (unknown_phase && dropped % 6) {
                        // Every remainder subset must preserve both survival
                        // and a reachable ignition. Never continue on a guessed
                        // remainder board; return one move and reobserve it.
                        drop_cases = 0;
                        std::tuple<int,int,int,int> worst{100, 0, 0, 0};
                        for (unsigned mask = 0; mask < 64; ++mask) {
                            if (std::popcount(mask) != dropped % 6) continue;
                            ++drop_cases;
                            auto outcome = observed_result;
                            u8 heights[6]; outcome.get_heights(heights);
                            bool overflow = false;
                            for (int x = 0; x < 6; ++x) {
                                int amount = dropped / 6 + ((mask >> x) & 1);
                                overflow |= heights[x] + amount > 13;
                                for (int n = 0; n < amount && heights[x] < 13; ++n)
                                    outcome.set_cell(x, heights[x]++, cell::Type::GARBAGE);
                            }
                            bool survives = !overflow && !outcome.is_dead(rules);
                            drop_alive &= survives;
                            auto p = potential(outcome, rules);
                            drop_target_preserved &= p.chain >= target;
                            auto rank = std::make_tuple(int(survives),
                                build_value(outcome, p, int(child.path.size()) + 1, child.frame), p.chain, -p.residue);
                            if (rank < worst) { worst = rank; child.field = outcome; }
                        }
                    } else drop_nuisance(child.field, dropped, child.phase);
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
                if (unknown_phase && dropped % 6) { step.has_all_cases = true; step.all_cases = drop_target_preserved; }
                step.timely_points = timely_points;
                for (const auto point : points) step.total_points += point;
                step.completed = chain && (count_chain ? end_at : fire_at) + safety < remaining;
                step.next_fits = chain &&
                    (count_chain ? end_at : fire_at) + spawn + placement + 15 + safety < remaining;
                step.points = std::move(points);
                child.path.push_back(std::move(step));
                consider(child, chain, alive, fire_at, end_at, sent);
                if (depth == 0 && alive && !chain) {
                    // consider() has already measured this board when the strategy extends
                    const auto& last = child.path.back();
                    const int reach = last.has_extension ? last.extension.chain : potential(child.field, rules).chain;
                    root_build_preserves_target |= reach >= target && last.all_cases_preserve();
                }
                if (alive && !chain && field_known && end_at + spawn + safety < remaining) {
                    child.frame = end_at + spawn;
                    next.push_back(std::move(child));
                }
            }
            if (cutoff) break;
        }
        if (depth == 0 && !cutoff) root_complete = true;
        // Preserve distinct boards and garbage state at each visible position.
        std::stable_sort(next.begin(), next.end(), [&](const SeedNode& a, const SeedNode& b) {
            return strategy == "extend" ? std::make_tuple(a.build_value, -a.frame) >
                std::make_tuple(b.build_value, -b.frame) : a.frame < b.frame;
        });
        std::unordered_set<std::string> seen; layer.clear();
        for (auto& n : next) {
            std::string key;
            for (const auto& row : fever::text::from_field(n.field)) key += row;
            key += '|' + std::to_string(n.frame) + '|' + std::to_string(n.confirmed) + '|' + std::to_string(n.phase);
            if (seen.insert(key).second) layer.push_back(std::move(n));
            if (layer.size() >= size_t(width)) break;
        }
    }
    if (best_path.empty()) throw std::invalid_argument("no conservative legal placement");
    const auto& last = best_path.back();
    const bool solved = !last.dead && last.chain >= target && last.fire_at + safety < remaining;
    const bool intentional_failure = root_complete && root.confirmed > 0 && !root_build_preserves_target &&
        !best_path[0].dead && best_path[0].chain > 0 && best_path[0].chain < target;
    json line = json::array();
    for (auto& step : best_path) line.push_back(step.describe());
    return {{"choice", line[0]}, {"path", line}, {"solved", solved},
        {"target_chain", target}, {"expanded", expanded}, {"cutoff", cutoff},
        {"requires_new_seed_after_clear", best_path.back().chain > 0},
        {"searched_visible", queue.size()}, {"pending_arrival_status", "unconfirmed_not_scheduled"},
        {"strategy", strategy},
        {"seed_color_needs", color_needs(field).describe(pieces, 0)},
        {"intentional_seed_failure", intentional_failure},
        {"failure_avoidance_status", intentional_failure ? "confirmed_drop_blocks_required_ignition" : "not_proven_required"},
        {"objective", strategy == "quick" ? "deadline_score_and_seed_turnover" : "max_chain_for_next_fever_entry"},
        {"extension_moves", extension_moves}, {"extension_patience", patience}, {"desired_chain", target + gain},
        {"clock_policy", count_chain ? "counts_chain" : "stops_during_chain"}};
}
}

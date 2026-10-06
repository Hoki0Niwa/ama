#include "search.h"
#include "../fever/text.h"
#include "physics.h"
#include "timing.h"
#include "color_needs.h"
#include "rate_schedule.h"
#include "transition.h"
#include <chrono>
#include <bit>
#include <tuple>
#include <unordered_set>
#include <functional>

namespace fever_battle {
using json = nlohmann::json;
namespace {
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
    bool has_all_cases = false, all_cases = true, keeps_ignition = true, completed = false, next_fits = false;
    bool has_extension = false, target_preserved = false;
    int time_reward = 0, remaining_after_rewards = 0;
    i64 carry = 0;      // nuisance left for the normal board if Fever ended after this step
    Potential extension;
    i64 worth = 0;      // points expected by the end of the Fever
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
            {"carried_nuisance", carry}};
        if (has_all_cases) {
            j["all_drop_cases_preserve_target"] = all_cases;
            j["all_drop_cases_keep_ignition"] = keeps_ignition;
        }
        if (has_extension) {
            j["extension_potential"] = {{"chain", extension.chain}, {"needed_cells", extension.needed},
                {"remaining_cells", extension.residue}, {"status", "geometric_heuristic_not_visible_solution"}};
            j["target_ignition_preserved"] = target_preserved;
        }
        j["expected_points"] = worth;
        return j;
    }
};
struct SeedNode {
    Field field;
    int frame = 0, confirmed = 0, flying = 0, held = 0, phase = 0;
    i64 remainder = 0;
    i64 enemy_fixed = 0, enemy_flying = 0, enemy_remainder = 0;
    size_t event_index = 0;
    std::vector<Step> path;
    int value = 0;      // of the line so far: which nodes go on to the next piece
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
    const int max_nodes = number(request, "max_nodes", 1, 100000);
    const int budget_ms = number(request, "budget_ms", 1, 1000);
    // Steam build 15209927's internal Fever timer caps at 1860 frames.
    // The Python protocol validates the caller's explicit clock domain.
    const int remaining = number(request, "remaining_frames", 0, 1860);
    const int maximum = request.contains("maximum_frames") ? number(request, "maximum_frames", 1800, 1860) : 1800;
    const int target = number(request, "seed_chain", 3, 15);
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
    if (!powers.is_array() || powers.size() != 17)
        throw std::invalid_argument("17 Fever powers required");
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
    auto rules = rule::FEVER; rules.plain_pairs = true;
    if (field.is_dead(rules)) throw std::invalid_argument("already dead field");
    SeedNode root; root.field = field;
    root.confirmed = number(request, "confirmed", 0, 1000000000);
    root.flying = number(request, "unconfirmed", 0, 1000000000);
    root.held = number(request, "held_pending", 0, 1000000000);
    root.remainder = number(request, "remainder", 0, 1000000000);
    root.phase = number(request, "garbage_phase", 0, 5);
    root.enemy_fixed = request.contains("enemy_confirmed") ? number(request, "enemy_confirmed", 0, 1000000000) : 0;
    root.enemy_flying = request.contains("enemy_unconfirmed") ? number(request, "enemy_unconfirmed", 0, 1000000000) : 0;
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
        advance_enemy(events, rates, until, state.event_index, state.confirmed, state.flying,
            state.enemy_fixed, state.enemy_flying, state.enemy_remainder);
        state.frame = until;
    };
    const auto start = std::chrono::steady_clock::now();
    std::vector<SeedNode> layer{root};
    std::vector<Step> best_path;
    std::tuple<int, i64, int, int, int, i64> best_rank{-1, 0, 0, 0, 0, 0};
    int expanded = 0; bool cutoff = false;
    bool root_complete = false, root_build_preserves_target = false;
    // One measure for every line, the points expected by
    // the end of this Fever. A fire is worth its own points and what the
    // seeds after it can still score on the clock it leaves; a line that pops
    // nothing is worth the chain it has built, by the odds that the puyos it
    // waits for come. The model below is a template (one colour, four puyos a
    // link, fixed odds), not a forecast of the seeds or the colours to come.
    const auto template_points = [&](int chain) {
        i64 total = 0;
        for (int i = 0; i < chain && i < int(power_table.size()); ++i)
            total += 40 * std::clamp(power_table[i] + bonuses.group.at(4) + bonuses.color.at(1),
                bonuses.minimum, bonuses.maximum);
        return total;
    };
    const auto next_level = [&](int chain, bool all_clear) {
        const int level = chain >= target ? chain + 1 : target - std::min(2, std::max(0, target - chain - 1));
        return std::clamp(level + (all_clear ? 2 : 0), 3, 15);
    };
    const int setup_frames = 2 * (placement + spawn);
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
    const auto future = [&](int level, int clock) {
        double total = 0, odds = 1;
        for (int k = 0; k < 24 && clock > setup_frames + first_link + safety; ++k) {
            total += odds * template_points(level);
            clock -= setup_frames + chain_frames(level);
            if (clock <= 0) break;          // that chain outlasts the clock: it scores, nothing follows
            clock = std::min(maximum, clock + std::max(0, level - 2) * 30) - chain_ready;
            odds *= SEED_ODDS; level = std::min(15, level + 1);
        }
        return total + odds * CARRIED_LEVEL * template_points(level);
    };
    double COLOR_ODDS[4] = {0, 0.75, 0.45, 0.25};               // 1, 2 or 3 puyos of one colour come in time
    if (model.contains("color_odds")) {
        const auto& odds = model.at("color_odds");
        if (!odds.is_array() || odds.size() != 3) throw std::invalid_argument("color_odds needs three values");
        for (int i = 0; i < 3; ++i) {
            if (!odds[i].is_number() || odds[i] < 0 || odds[i] > 1) throw std::invalid_argument("color_odds out of range");
            COLOR_ODDS[i + 1] = odds[i].get<double>();
        }
    }
    // Points that offset are worth what they stop, the same as points sent, so
    // nuisance pending is no separate term: more points is less of it. Only
    // what the stored board cannot take at the end weighs beyond that.
    // A nuisance the stored board cannot take, in the points of this many sent
    const double HARMFUL_CARRY = model_number("harmful_carry", 10);
    const auto danger = [&](i64 carry, double points_to_come) {
        const double left = std::max(0.0, double(carry) - points_to_come / rate);
        return std::max(0.0, left - double(std::max<i64>(0, quiet_limit))) * rate * HARMFUL_CARRY;
    };
    const auto consider = [&](SeedNode& node, int chain, bool alive, int fire_at, int end_at, i64 sent) {
        auto& last = node.path.back();
        const bool in_time = (chain ? fire_at : end_at) + safety < remaining;
        const int tier = alive && in_time ? 3 : alive ? 2 : 1;
        const int reward_clear = chain && node.field.is_empty() && in_time ? 1 : 0;
        double worth = 0;
        if (chain) {
            // An in-time ignition scores the whole chain, even if it ends after the clock.
            const int clock = last.completed ? last.remaining_after_rewards - chain_ready : 0;
            const double later = future(next_level(chain, last.all_clear), clock);
            worth = double(last.total_points) + later - danger(last.carry, later);
        } else {
            const auto p = potential(node.field, rules);
            last.has_extension = true; last.extension = p;
            last.target_preserved = p.chain >= target && last.all_cases_preserve();
            const int wait = p.needed * (placement + spawn);
            const bool reachable = p.chain > 0 && end_at + wait + first_link + safety < remaining;
            const double odds = reachable ? COLOR_ODDS[std::clamp(p.needed, 1, 3)] : 0;
            int clock = remaining - end_at - wait - chain_frames(p.chain);
            if (clock > 0) clock = std::min(maximum, clock + std::max(0, p.chain - 2) * 30) - chain_ready;
            const double hit = template_points(p.chain) + future(next_level(p.chain, false), clock);
            // The puyos do not come and nothing is fired: the seed and its level are kept.
            const double miss = CARRIED_LEVEL * template_points(target);
            worth = odds * (hit - danger(last.carry, hit)) + (1 - odds) * (miss - danger(last.carry, 0));
        }
        const i64 value = i64(worth);
        node.value = int(std::clamp<i64>(value, -2000000000, 2000000000));
        last.worth = value;
        const auto rank = std::make_tuple(tier, value, reward_clear, chain, -end_at, sent);
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
                advance(child, child.frame + placement + split_costs[split].get<int>());
                if (!child.field.drop_piece(moves[i].x, moves[i].r, pieces[depth], rules)) continue;
                auto locked = child.field;
                auto masks = child.field.pop();
                auto features = fall_features(locked, masks);
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
                    if (i64(child.confirmed) + child.flying + child.held && amount == 0) amount = 1;
                    for (int* pending : {&child.confirmed, &child.flying, &child.held}) {
                        int n = int(std::min<i64>(*pending, amount));
                        *pending -= n; amount -= n; cancelled += n;
                    }
                    sent += amount;
                    child.enemy_flying += amount;
                    end_at += link_frames(features[k], k == chain - 1, pop_frames, settle_frames);
                }
                int dropped = 0, drop_cases = 1;
                bool drop_alive = true, drop_target_preserved = true, drop_keeps_ignition = true;
                std::vector<Field> drop_boards;
                auto observed_result = child.field;
                if (!chain) {
                    advance(child, child.frame + timing.value("nuisance_check_frames", 0));
                    dropped = std::min(30, child.confirmed); child.confirmed -= dropped;
                    if (unknown_phase && dropped % 6) {
                        // Every remainder subset must preserve both survival
                        // and a reachable ignition. Never continue on a guessed
                        // remainder board; return one move and reobserve it.
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
                for (const auto& feature : features) if (contact_frames(feature)) error += 2;
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
                // A drop taken on the Fever board leaves with it; one that locks
                // after the clock has run out is not counted as taken.
                step.carry = i64(child.held) + child.confirmed + child.flying +
                    (dropped && end_at + safety >= remaining ? dropped : 0);
                child.path.push_back(std::move(step));
                consider(child, chain, alive, fire_at, end_at, sent);
                if (depth == 0 && alive && !chain) {
                    const auto& last = child.path.back();
                    root_build_preserves_target |= last.extension.chain >= target && last.all_cases_preserve();
                }
                if (alive && !chain && !dropped && field_known &&
                    end_at + std::max(0, spawn-timing.value("nuisance_check_frames", 0)) + safety < remaining) {
                    advance(child, end_at + std::max(0, spawn-timing.value("nuisance_check_frames", 0)));
                    next.push_back(std::move(child));
                }
            }
            if (cutoff) break;
        }
        if (depth == 0 && !cutoff) root_complete = true;
        // Preserve distinct boards and garbage state at each visible position.
        std::stable_sort(next.begin(), next.end(), [&](const SeedNode& a, const SeedNode& b) {
            return std::make_tuple(a.value, -a.frame) > std::make_tuple(b.value, -b.frame);
        });
        std::unordered_set<std::string> seen; layer.clear();
        for (auto& n : next) {
            auto key = state_key(n.field, n.frame, n.confirmed, n.flying, n.held, n.remainder, n.phase,
                n.event_index, n.enemy_fixed, n.enemy_flying, n.enemy_remainder);
            if (seen.insert(key).second) layer.push_back(std::move(n));
            if (layer.size() >= size_t(width)) break;
        }
    }
    if (best_path.empty()) throw std::invalid_argument("no conservative legal placement");
    // The line ranked first stands: nothing is swapped in after the search.
    const auto& last = best_path.back();
    const bool solved = !last.dead && last.chain >= target && last.fire_at + safety < remaining;
    const bool deadline_failure = root.held && count_chain && !best_path[0].dead &&
        best_path[0].chain > 0 && best_path[0].chain < target &&
        best_path[0].end_at >= remaining + safety;
    const bool emergency_failure = root_complete && root.confirmed > 0 && !root_build_preserves_target &&
        !best_path[0].dead && best_path[0].chain > 0 && best_path[0].chain < target;
    const bool intentional_failure = deadline_failure || emergency_failure;
    json line = json::array();
    for (auto& step : best_path) line.push_back(step.describe());
    return {{"choice", line[0]}, {"path", line}, {"solved", solved},
        {"target_chain", target}, {"expanded", expanded}, {"cutoff", cutoff},
        {"requires_new_seed_after_clear", best_path.back().chain > 0},
        {"new_seed_spawn_possible", last.chain > 0 && (count_chain ? last.end_at < remaining+safety : last.fire_at < remaining)},
        {"requires_reobservation_after_drop", best_path.back().dropped > 0},
        {"searched_visible", queue.size()}, {"pending_arrival_status", events.empty() ? "unconfirmed_not_scheduled" : "observed_enemy_chain_timeline"},
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

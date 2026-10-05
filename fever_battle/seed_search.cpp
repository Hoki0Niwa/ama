#include "search.h"
#include "../fever/text.h"
#include "physics.h"
#include "timing.h"
#include <chrono>
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
struct SeedNode {
    Field field;
    int frame = 0, confirmed = 0, flying = 0, held = 0, phase = 0;
    i64 remainder = 0;
    json path = json::array();
};
void drop_nuisance(Field& field, int count, int phase) {
    constexpr int order[] = {0, 3, 2, 5, 1, 4};
    u8 heights[6]; field.get_heights(heights);
    int amounts[6]; for (auto& n : amounts) n = count / 6;
    for (int i = 0; i < count % 6; ++i) ++amounts[order[(phase + i) % 6]];
    for (int x = 0; x < 6; ++x) for (int i = 0; i < amounts[x]; ++i)
        if (heights[x] < 13) field.set_cell(x, heights[x]++, cell::Type::GARBAGE);
}
json points_for(avec<Field, 19>& masks, const json& powers, const json& bonuses) {
    json points = json::array();
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
    const int remaining = number(request, "remaining_frames", 0, 1800);
    const int target = number(request, "seed_chain", 3, 15);
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
    json best_path;
    std::tuple<int, int, int, int, int, i64> best_rank{-1, 0, 0, 0, 0, 0};
    int expanded = 0; bool cutoff = false;
    const auto consider = [&](SeedNode& node, int chain, bool alive, int fire_at, int end_at, i64 sent) {
        const bool in_time = (chain ? fire_at : end_at) + safety < remaining;
        const bool completed = (count_chain ? end_at : fire_at) + safety < remaining;
        const bool success = chain >= target && in_time && alive;
        // Successful short routes first. If unsolved, return a legal surviving
        // move; never continue building after the first clear replaces a seed.
        int tier = success ? 5 : alive && chain && in_time ? 4 : alive && in_time ? 3 : alive ? 2 : 1;
        const int reward_clear = chain && node.field.is_empty() && completed ? 1 : 0;
        auto rank = strategy == "quick"
            ? std::make_tuple(tier, -int(node.path.size()), chain, reward_clear, -end_at, sent)
            : std::make_tuple(tier, chain, reward_clear, -int(node.path.size()), -end_at, sent);
        if (rank > best_rank) { best_rank = rank; best_path = node.path; }
    };
    for (size_t depth = 0; depth < pieces.size() && !layer.empty() && !cutoff; ++depth) {
        std::vector<SeedNode> next;
        for (auto& parent : layer) {
            auto moves = move::generate(parent.field, pieces[depth], rules);
            for (int i = 0; i < moves.get_size(); ++i) {
                // Always establish an executable root fallback before honoring
                // CPU/node cutoffs. Budget termination returns a complete JSON.
                const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::steady_clock::now() - start).count();
                if (!best_path.is_null() && (expanded >= max_nodes || elapsed >= budget_ms)) {
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
                i64 sent = 0, cancelled = 0;
                for (int k = 0; k < chain; ++k) {
                    i64 total = points[k].get<i64>() + child.remainder;
                    i64 amount = total / rate; child.remainder = total % rate;
                    if (i64(child.confirmed) + child.flying + child.held && amount == 0) amount = 1;
                    for (int* pending : {&child.confirmed, &child.flying, &child.held}) {
                        int n = int(std::min<i64>(*pending, amount));
                        *pending -= n; amount -= n; cancelled += n;
                    }
                    sent += amount;
                    end_at += link_frames(features[k], k == chain - 1);
                }
                int dropped = 0;
                if (!chain) {
                    dropped = std::min(30, child.confirmed); child.confirmed -= dropped;
                    drop_nuisance(child.field, dropped, child.phase);
                    child.phase = (child.phase + dropped) % 6;
                    end_at = child.frame;
                }
                bool alive = !child.field.is_dead(rules);
                child.path.push_back({{"x", moves[i].x}, {"r", std::string(1, fever::text::from_direction(moves[i].r))},
                    {"field", fever::text::from_field(child.field)}, {"locked_field", fever::text::from_field(locked)},
                    {"chain", chain}, {"link_points", points}, {"all_clear", child.field.is_empty()},
                    {"fire_at", fire_at}, {"end_at", end_at}, {"dead", !alive}, {"dropped", dropped},
                    {"cancelled", cancelled}, {"sent", sent}, {"garbage_phase", child.phase}});
                consider(child, chain, alive, fire_at, end_at, sent);
                if (alive && !chain && end_at + spawn + safety < remaining) {
                    child.frame = end_at + spawn;
                    next.push_back(std::move(child));
                }
            }
            if (cutoff) break;
        }
        // Preserve distinct boards and garbage state at each visible position.
        std::stable_sort(next.begin(), next.end(), [](const SeedNode& a, const SeedNode& b) {
            return a.frame < b.frame;
        });
        std::unordered_set<std::string> seen; layer.clear();
        for (auto& n : next) {
            const auto key = json{{"field", fever::text::from_field(n.field)}, {"frame", n.frame},
                {"confirmed", n.confirmed}, {"phase", n.phase}}.dump();
            if (seen.insert(key).second) layer.push_back(std::move(n));
            if (layer.size() >= size_t(width)) break;
        }
    }
    if (best_path.is_null()) throw std::invalid_argument("no conservative legal placement");
    return {{"choice", best_path[0]}, {"path", best_path}, {"solved", std::get<0>(best_rank) == 5},
        {"target_chain", target}, {"expanded", expanded}, {"cutoff", cutoff},
        {"requires_new_seed_after_clear", best_path.back()["chain"].get<int>() > 0},
        {"searched_visible", queue.size()}, {"pending_arrival_status", "unconfirmed_not_scheduled"},
        {"strategy", strategy},
        {"clock_policy", count_chain ? "counts_chain" : "stops_during_chain"}};
}
}

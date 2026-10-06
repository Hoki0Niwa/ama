#include "search.h"
#include "rate_schedule.h"
#include "../fever/search.h"
#include "../fever/text.h"
#include "physics.h"
#include "timing.h"
#include "color_needs.h"
#include <unordered_set>

namespace fever_battle {
using json = nlohmann::json;
namespace {
// The next remainder resumes after the last actually dropped nuisance puyo.
constexpr int ORDER[] = {0, 3, 2, 5, 1, 4};
struct State {
    beam::node::Data node;
    i64 fixed = 0, flying = 0, remainder = 0, sent = 0;
    i64 credit = 0, value = 0;
    int needed_loss = 0;
    int phase = 0;
    int frame = 0, event_index = 0;
    i64 enemy_fixed = 0, enemy_flying = 0, enemy_remainder = 0;
    json path = json::array();
    bool seed = false;
};
i64 number(const json& j, const char* key, i64 low, i64 high) {
    const auto& v = j.at(key);
    if (!v.is_number_integer() || v < low || v > high)
        throw std::invalid_argument(std::string(key) + " out of range");
    return v.get<i64>();
}
int garbage(Field& field, int count, int phase) {
    u8 heights[6]; field.get_heights(heights);
    int amounts[6]; for (auto& n : amounts) n = count / 6;
    for (int i = 0; i < count % 6; ++i) ++amounts[ORDER[(phase + i) % 6]];
    int discarded = 0;
    for (int x = 0; x < 6; ++x) for (int i = 0; i < amounts[x]; ++i) {
        if (heights[x] >= 13) ++discarded;
        else field.set_cell(x, heights[x]++, cell::Type::GARBAGE);
    }
    return discarded;
}
json links_and_points(avec<Field, 19>& masks, const json& powers, const json& bonus) {
    json links = json::array(), points = json::array();
    for (int i = 0; i < masks.get_size(); ++i) {
        auto mask = masks[i]; int colors = 0, total = 0, group_bonus = 0;
        json groups = json::array();
        for (int c = 0; c < cell::COUNT - 1; ++c) {
            if (mask.data[c].is_empty()) continue;
            ++colors;
            while (!mask.data[c].is_empty()) {
                auto group = mask.data[c].get_mask_group_lsb();
                const int n = group.get_count(); total += n;
                groups.push_back(n); group_bonus += bonus.at("group").at(std::min(11, n)).get<int>();
                mask.data[c] = mask.data[c] & ~group;
            }
        }
        int multiplier = std::clamp(powers.at(i).get<int>() + group_bonus + bonus.at("color").at(colors).get<int>(),
            bonus.at("multiplier_min").get<int>(), bonus.at("multiplier_max").get<int>());
        links.push_back({{"groups", groups}, {"colors", colors}});
        points.push_back(10 * total * multiplier);
    }
    return {{"links", links}, {"points", points}};
}
}

json search(Field field, const json& request) {
    const auto width = number(request, "width", 1, 1000);
    const auto rate = number(request, "target_point", 1, 100000);
    const RateSchedule rates(request, int(rate));
    const auto weights = request.at("weights");
    const auto w = weights.get<beam::eval::Weight>();
    fever::Configs configs; configs.hill = weights.value("hill", 0);
    auto rules = rule::FEVER; rules.plain_pairs = true;
    const auto queue = request.at("queue").get<std::vector<std::string>>();
    if (queue.empty() || queue.size() > 3) throw std::invalid_argument("search uses current plus NEXT2 only");
    std::vector<piece::Piece> pieces;
    for (const auto& text : queue) {
        auto p = fever::text::to_piece(text);
        if (!p) throw std::invalid_argument("invalid visible piece");
        pieces.push_back(*p);
    }
    const auto powers = request.at("powers"), bonus = request.at("bonuses");
    const auto events = request.value("enemy_events", json::array());
    if (!events.is_array()) throw std::invalid_argument("enemy_events must be an array");
    int previous = -1;
    for (const auto& event : events) {
        const int at = int(number(event, "frame", 0, 1000000));
        if (at < previous) throw std::invalid_argument("enemy events must be ordered");
        previous = at;
        if (event.at("type") != "end") {
            if (event.at("type") != "link") throw std::invalid_argument("unknown enemy event");
            number(event, "points", 1, 1000000000);
        }
    }
    const auto timing = request.at("timing");
    const int placement_frames = int(number(timing, "placement_frames", 1, 10000));
    const int pop_frames = int(number(timing, "pop_frames", 1, 10000));
    const int score_offset = timing.contains("score_offset_frames")
        ? int(number(timing,"score_offset_frames",0,pop_frames)) : pop_frames;
    const int fall_frames = int(number(timing, "fall_frames_per_row", 0, 10000));
    const int settle_frames = int(number(timing, "settle_frames", 0, 10000));
    const int spawn_frames = int(number(timing, "spawn_frames", 0, 10000));
    const bool geometry_timing=timing.value("geometry_timing",false);
    const int first_link_frames=timing.contains("first_link_frames") ? int(number(timing,"first_link_frames",0,10000)) : 0;
    const int chain_ready_frames=timing.contains("chain_ready_frames") ? int(number(timing,"chain_ready_frames",0,10000)) : spawn_frames;
    const auto split_costs = timing.value("split_extra_frames", json::array());
    if (!split_costs.empty()) {
        if (!split_costs.is_array() || split_costs.size()!=14) throw std::invalid_argument("split duration table must have 14 entries");
        for (const auto& cost : split_costs)
            if (!cost.is_null() && (!cost.is_number_integer() || cost<0 || cost>10000))
                throw std::invalid_argument("invalid split duration");
    }
    if (powers.size() != 19) throw std::invalid_argument("19 character powers required");
    State root; root.node.field = field;
    root.fixed = number(request, "confirmed", 0, 1000000000);
    root.flying = number(request, "unconfirmed", 0, 1000000000);
    root.remainder = number(request, "remainder", 0, 1000000000);
    root.phase = int(number(request, "garbage_phase", 0, 5));
    root.enemy_fixed = number(request, "enemy_confirmed", 0, 1000000000);
    root.enemy_flying = number(request, "enemy_unconfirmed", 0, 1000000000);
    root.enemy_remainder = number(request, "enemy_remainder", 0, 1000000000);
    // Process predicted opposing links causally. Offsetting now cannot erase a link
    // that the opponent has not scored yet; own excess attacks can offset it later.
    const auto advance = [&](State& state, int until) {
        while (state.event_index < int(events.size()) && events[state.event_index]["frame"].get<int>() <= until) {
            const auto& event = events[state.event_index++];
            if (event["type"] == "end") { state.fixed += state.flying; state.flying = 0; }
            else {
                i64 total = event["points"].get<i64>() + state.enemy_remainder;
                const int active_rate = rates.at(event["frame"].get<int>(), true);
                i64 amount = total / active_rate; state.enemy_remainder = total % active_rate;
                if (state.enemy_fixed + state.enemy_flying && amount == 0) amount = 1;
                auto n = std::min(state.enemy_fixed, amount); state.enemy_fixed -= n; amount -= n;
                n = std::min(state.enemy_flying, amount); state.enemy_flying -= n; amount -= n;
                state.flying += amount;
            }
        }
        state.frame = until;
    };
    if (field.is_dead(rules)) throw std::invalid_argument("already dead field");
    const auto needs = color_needs(field);
    std::vector<State> layer{root};
    std::optional<State> best;
    size_t best_depth = 0, expanded = 0, deaths = 0;
    for (size_t depth = 0; depth < pieces.size() && !layer.empty(); ++depth) {
        std::vector<State> next;
        for (auto& parent : layer) {
            auto locks = move::generate(parent.node.field, pieces[depth], rules);
            for (int i = 0; i < locks.get_size(); ++i) {
                ++expanded;
                State child = parent;
                advance(child, child.frame + placement_frames);
                auto splits = split_distances(child.node.field, pieces[depth], locks[i].x, locks[i].r);
                int split_rows = *std::max_element(splits.begin(), splits.end());
                bool split_measured = !split_costs.empty() && !split_costs[split_rows].is_null();
                int split_extra = split_measured ? split_costs[split_rows].get<int>() : split_rows * fall_frames;
                auto drop = child.node.field.drop_piece(locks[i].x, locks[i].r, pieces[depth], rules);
                if (!drop) continue;
                advance(child, child.frame + split_extra);
                const auto before_pop = child.node.field;
                auto popped = child.node.field.pop();
                for (int k = 0; k < popped.get_size(); ++k) for (int c = 0; c < 4; ++c)
                    child.needed_loss += popped[k].data[c].get_count() * needs.reserve[c];
                const auto falls = fall_distances(before_pop, popped);
                const auto features = fall_features(before_pop,popped);
                auto detail = links_and_points(popped, powers, bonus);
                const auto placement_field = fever::text::from_field(child.node.field);
                int dropped = 0, discarded = 0; i64 cancelled = 0, sent = 0;
                if (popped.get_size()) {
                    advance(child,child.frame+first_link_frames);
                    int link_index = 0;
                    for (const auto& point : detail["points"]) {
                        advance(child, child.frame + score_offset);
                        i64 total = point.get<i64>() + child.remainder;
                        const int active_rate = rates.at(child.frame);
                        i64 amount = total / active_rate; child.remainder = total % active_rate;
                        if (child.fixed + child.flying && amount == 0) amount = 1;
                        auto n = std::min(child.fixed, amount); child.fixed -= n; amount -= n; cancelled += n;
                        n = std::min(child.flying, amount); child.flying -= n; amount -= n; cancelled += n;
                        child.sent += amount; sent += amount;
                        child.enemy_flying += amount;
                        const int duration=geometry_timing ? link_frames(features[link_index],link_index==popped.get_size()-1)
                            : pop_frames+settle_frames+falls[link_index]*fall_frames;
                        ++link_index;
                        advance(child,child.frame+duration-score_offset);
                    }
                    child.enemy_fixed += child.enemy_flying; child.enemy_flying = 0;
                    // Credit the chain actually realized, using the adopted chain weight.
                    child.credit += i64(popped.get_size()) * w.chain;
                    child.seed = child.node.field.is_empty();
                } else {
                    // Delivery is checked after lock/split, not at first contact.
                    advance(child, child.frame + timing.value("nuisance_check_frames", 0));
                    dropped = int(std::min<i64>(30, child.fixed)); child.fixed -= dropped;
                    discarded = garbage(child.node.field, dropped, child.phase);
                    if (dropped) child.phase = (child.phase + dropped) % 6;
                }
                if (child.node.field.is_dead(rules)) { ++deaths; continue; }
                beam::eval::action(child.node, drop->split, popped.get_size(), w);
                fever::evaluate(child.node, w, configs);
                // Apply the existing per-puyo nuisance penalty to held packets as well as terrain.
                child.value = i64(child.node.score.eval) + child.node.score.action + child.credit
                    + std::min<i64>(78, child.fixed + child.flying) * w.nuisance
                    + color_needs(child.node.field).quality(pieces, depth + 1) - child.needed_loss * 80;
                child.path.push_back({{"x", locks[i].x}, {"r", std::string(1, fever::text::from_direction(locks[i].r))},
                    {"links", detail["links"]}, {"link_points", detail["points"]},
                    {"placement_field", placement_field}, {"field", fever::text::from_field(child.node.field)},
                    {"dropped", dropped}, {"discarded", discarded}, {"cancelled", cancelled}, {"sent", sent},
                    {"confirmed", child.fixed}, {"unconfirmed", child.flying}, {"remainder", child.remainder},
                    {"garbage_phase", child.phase},
                    {"frame", child.frame}, {"fall_distances", falls},
                    {"fall_features", features},
                    {"chain_timing_source",geometry_timing ? "steam_15209927_calibrated_estimate" : "explicit_linear_costs"},
                    {"split_distances", splits}, {"split_extra_frames", split_extra},
                    {"split_time_source", split_measured ? (split_rows<=9 ? "measured_rows_0_to_9" : "sqrt_extrapolation") : "prototype_extrapolation"},
                    {"all_clear_requires_observed_seed", child.seed}});
                child.path.back()["needed_color_consumed"] = child.needed_loss;
                // An all-clear ends at an unknown seed, never at a fictional empty-board continuation.
                const size_t survives = child.seed ? pieces.size() : depth + 1;
                if (!best || survives > best_depth || (survives == best_depth && child.value > best->value)) {
                    best = child; best_depth = survives;
                }
                if (!child.seed) {
                    advance(child, child.frame + (popped.get_size() ? chain_ready_frames :
                        std::max(0, spawn_frames-timing.value("nuisance_check_frames", 0))));
                    next.push_back(std::move(child));
                }
            }
        }
        std::stable_sort(next.begin(), next.end(), [](const State& a, const State& b) { return a.value > b.value; });
        // Merge only identical board AND nuisance/remainder states at this queue position.
        std::unordered_set<std::string> seen;
        layer.clear();
        for (auto& n : next) {
            auto key = json{{"field", fever::text::from_field(n.node.field)}, {"fixed", n.fixed},
                {"flying", n.flying}, {"remainder", n.remainder}, {"phase", n.phase},
                {"frame", n.frame}, {"event_index", n.event_index}, {"enemy_fixed", n.enemy_fixed},
                {"enemy_flying", n.enemy_flying}, {"enemy_remainder", n.enemy_remainder}}.dump();
            if (seen.insert(key).second) layer.push_back(std::move(n));
            if (layer.size() >= size_t(width)) break;
        }
    }
    if (!best) throw std::invalid_argument("no placement survives observed confirmed garbage");
    return {{"choice", best->path[0]}, {"path", best->path}, {"value", best->value},
        {"searched_visible", pieces.size()}, {"completed_moves", best->path.size()},
        {"horizon_complete", best->path.size() == pieces.size()}, {"stopped_at_unknown_seed", best->seed},
        {"expanded", expanded}, {"rejected_dead", deaths}, {"beam_width", width},
        {"color_needs", needs.describe(pieces, 0)},
        {"future_unconfirmed_arrival", events.empty() ? "unscheduled_not_dropped" : "predicted_chain_timeline"}};
}
}

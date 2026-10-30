#include "normal_followup.h"
#include "attack_timing.h"
#include "main_attack.h"
#include "../fever/normal_space.h"
#include "../fever/text.h"
#include <set>

namespace fever_battle {
using json = nlohmann::json;
namespace {
struct Node { Field field; json path = json::array(); int ready = 0; };
}

json normal_followup(Field field, const json& request) {
    const auto& options = request.at("options");
    const int min_garbage = number(options, "min_garbage", 1, 78);
    const int max_usable = number(options, "max_usable", 0, 78);
    const int max_nodes = number(options, "max_nodes", 1, 100000);
    const int depth = number(options, "depth", 1, 12);
    const int width = number(options, "width", 1, 128);
    const int gauge_step = number(options, "gauge_step_frames", 1, 3600);
    const int rate = number(request, "target_point", 1, 100000);
    const int remainder = number(request, "remainder", 0, 1000000000);
    const auto& enemy = request.at("enemy");
    const int gauge = number(enemy, "gauge", 0, 7);
    auto opponent = fever::text::to_field(enemy.at("field").get<std::vector<std::string>>());
    if (!opponent) throw std::invalid_argument("invalid enemy field");
    const int garbage = opponent->data[int(cell::Type::GARBAGE)].get_count();
    const int usable = gaze::get_unburied_count(*opponent);
    json result = {{"found", false}, {"enemy_usable", usable}, {"enemy_garbage", garbage},
                   {"model", "tsu_buried_followup_fever_gauge_guard"}};
    const auto powers = request.at("powers").get<std::vector<int>>();
    const auto enemy_powers = enemy.at("powers").get<std::vector<int>>();
    if (powers.size() != 19 || enemy_powers.size() != 19) throw std::invalid_argument("19 powers required");
    const Bonuses bonuses(request.at("bonuses"));
    const auto hold = main_attack::potential(*opponent, enemy_powers, bonuses);
    u8 heights[6]; opponent->get_heights(heights);
    const int min_height = *std::min_element(heights, heights+6);
    // Tsu's kill(): reserve their strongest held reply, then enough whole rows
    // to fill even their lowest column. Existing pending packets are not discounted.
    const i64 counter = (hold.first + number(enemy, "remainder", 0, 1000000000)) / rate;
    const i64 needed = counter + std::max(0, 12 - min_height) * 6;
    result.update({{"enemy_counter", counter}, {"enemy_counter_chain", hold.second},
                   {"need", needed}, {"enemy_min_height", min_height}});
    const i64 pending = enemy.value("pending", i64(0));
    result["lethal_pending"] = pending >= needed && pending > 0;
    if (result["lethal_pending"].get<bool>()) { result["blocked"] = "already_lethal_pending"; return result; }
    if (request.value("status_only", false) || gauge >= 4 || garbage < min_garbage || usable > max_usable)
        return result;
    fever::Queue pieces;
    const auto texts = request.at("queue").get<std::vector<std::string>>();
    if (texts.empty() || texts.size() > 12) throw std::invalid_argument("queue requires 1..12 pieces");
    for (const auto& text : texts) {
        auto piece = fever::text::to_piece(text);
        if (!piece) throw std::invalid_argument("invalid piece");
        pieces.push_back(*piece);
    }
    auto rules = rule::FEVER; rules.plain_pairs = rules.special_moves = true;
    const auto& timing = request.at("timing");
    const int gain = number(request, "gain", 0, 7);
    // A held chain capable of completing the gauge is an observed escape.
    // Unknown future digs remain a limitation of this Tsu-style estimate.
    if (gain && gauge + hold.second * gain >= 7) {
        result["blocked"] = "held_gauge_escape";
        return result;
    }
    std::vector<Node> layer{{field}};
    int expanded = 0, best_end = INT_MAX;
    i64 best_points = 0;
    bool cutoff = false;
    const int maximum_lock = request.value("maximum_lock", 1000000);
    for (int d = 0; d < std::min(depth, int(pieces.size())) && !layer.empty(); ++d) {
        std::vector<Node> next;
        std::set<std::string> seen;
        for (const auto& parent : layer) {
            auto moves = fever::normal_space::moves(parent.field, pieces[d], rules, d == 0);
            for (int i = 0; i < moves.get_size(); ++i) {
                if (expanded >= max_nodes) { cutoff = true; break; }
                ++expanded;
                auto child = parent;
                auto before = child.field;
                const auto splits = split_distances(before, pieces[d], moves[i].x, moves[i].r);
                if (!child.field.drop_piece(moves[i].x, moves[i].r, pieces[d], rules)) continue;
                auto locked = child.field;
                auto masks = child.field.pop();
                const int chain = masks.get_size();
                if (child.field.is_dead(rules)) continue;
                const auto times = attack_times(locked, masks, *std::max_element(splits.begin(), splits.end()),
                                                parent.ready, timing, request.value("pace_frames",0));
                if (times.lock > maximum_lock) continue;
                i64 points = 0;
                for (int k = 0; k < chain; ++k) points += score_link(masks[k], powers[k], bonuses).points;
                child.ready = times.ready;
                child.path.push_back({{"x", moves[i].x}, {"r", std::string(1,fever::text::from_direction(moves[i].r))},
                    {"chain", chain}, {"points", points}, {"field", fever::text::from_field(child.field)},
                    {"lock_frame",times.lock},{"attack_end",times.end}});
                if (chain) {
                    const i64 sent = (points + remainder) / rate;
                    const int limit = followup_gauge_limit(times.end, gauge_step);
                    if (gauge > limit || sent < needed || sent <= 0) continue;
                    if (times.end > best_end || (times.end == best_end && points <= best_points)) continue;
                    best_end = times.end; best_points = points;
                    result.update({{"found",true},{"choice",child.path[0]},{"path",child.path},
                        {"chain",chain},{"points",points},{"sent",sent},{"gauge_limit",limit},
                        {"attack_end",times.end},{"fire_moves",d+1}});
                } else {
                    if (times.ready >= best_end) continue;
                    const auto key = child.path.back()["field"].dump();
                    if (seen.insert(key).second) next.push_back(std::move(child));
                }
            }
            if (cutoff) break;
        }
        if (cutoff) break;
        // Near the top, free central space before considering longer setups.
        std::stable_sort(next.begin(), next.end(), [](const Node& a, const Node& b) {
            auto fa=a.field, fb=b.field;
            return std::max(fa.get_height(2),fa.get_height(3)) < std::max(fb.get_height(2),fb.get_height(3));
        });
        if (next.size() > size_t(width)) next.resize(width);
        layer = std::move(next);
    }
    result.update({{"expanded",expanded},{"budget_exhausted",cutoff},{"searched_visible",pieces.size()}});
    return result;
}
}

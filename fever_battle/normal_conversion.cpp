#include "normal_conversion.h"
#include "transition.h"
#include "attack_timing.h"
#include "../fever/search.h"
#include "../fever/normal_space.h"
#include "../fever/text.h"
#include <map>
#include <set>
#include <tuple>

namespace fever_battle {
using json = nlohmann::json;
namespace {
struct Node {
    Field field;
    json path = json::array();
    i64 rank = 0;
    int chain = 0, points = 0, sent = 0, remaining = 0, ready = 0, end = 0, gross = 0;
};
struct Recovery {
    bool viable = false;
    i64 points = 0;
    int min_chain = 0, max_chain = 0, next_safe = 0;
    json chains = json::array(), depths = json::array();
};
int colored(Field field) {
    int n = 0;
    for (int c = 0; c < cell::COUNT - 1; ++c) n += field.data[c].get_count();
    return n;
}
int quiet_moves(Field field, const piece::Piece& piece, const rule::Rule& rules) {
    auto moves = fever::normal_space::moves(field, piece, rules);
    int count = 0;
    for (int i = 0; i < moves.get_size(); ++i) {
        auto after = field;
        if (!after.drop_piece(moves[i].x, moves[i].r, piece, rules)) continue;
        if (after.pop_count() || !fever::normal_space::room(after, 0)) continue;
        ++count;
    }
    return count;
}
// All six bags must have a common next placement and a nontrivial recovery.
// These are projections, never steps appended to the executable firing path.
Recovery recover(Field field, const fever::Queue& known, const dropset::Character& character,
                 u64 index, const beam::eval::Weight& weights, fever::Configs cfg,
                 int minimum_chain, int minimum_safe) {
    struct Total {
        int count = 0, min_chain = 19, max_chain = 0;
        i64 points = 0;
        json chains = json::array();
    };
    std::map<std::pair<int,int>, Total> totals;
    Recovery result;
    result.next_safe = 1000;
    for (int bag = 0; bag < fever::VIRTUAL_COUNT; ++bag) {
        auto queue = known;
        if (queue.size() < cfg.depth) {
            auto tail = fever::create_queue_virtual(character, bag, cfg.depth - queue.size(), index + queue.size());
            if (!tail) return {};
            queue.insert(queue.end(), tail->begin(), tail->end());
        }
        if (queue.empty()) return {};
        result.next_safe = std::min(result.next_safe, quiet_moves(field, queue[0], cfg.rules));
        if (result.next_safe < minimum_safe) return {};
        const auto search = fever::search(field, queue, weights, cfg);
        result.depths.push_back(search.completed_depth);
        for (const auto& candidate : search.candidates) {
            if (candidate.next_room <= 0) continue;
            auto& total = totals[{candidate.placement.x, int(candidate.placement.r)}];
            ++total.count;
            total.points += candidate.score;
            total.min_chain = std::min(total.min_chain, candidate.chain);
            total.max_chain = std::max(total.max_chain, candidate.chain);
            total.chains.push_back(candidate.chain);
        }
    }
    for (const auto& [move, total] : totals) {
        if (total.count != fever::VIRTUAL_COUNT || total.min_chain < minimum_chain) continue;
        if (result.viable && total.points <= result.points * fever::VIRTUAL_COUNT) continue;
        result.viable = true;
        result.points = total.points / fever::VIRTUAL_COUNT;
        result.min_chain = total.min_chain;
        result.max_chain = total.max_chain;
        result.chains = total.chains;
    }
    return result;
}
}

json normal_conversion(Field field, const json& request) {
    const auto& options = request.at("options");
    const int max_chain = number(options, "max_chain", 1, 5);
    const int horizon = number(options, "depth", 1, 12);
    const int width = number(options, "width", 1, 128);
    const int max_nodes = number(options, "max_nodes", 1, 100000);
    const int shortlist = number(options, "shortlist", 1, 24);
    const int min_sent = number(options, "min_sent", 1, 10000);
    const int min_material = number(options, "min_material", 4, 78);
    const int min_safe = number(options, "min_safe", 1, 24);
    const int min_recovery = number(options, "min_recovery", 1, 19);
    const int rate = number(request, "target_point", 1, 100000);
    const int remainder = number(request, "remainder", 0, 1000000000);
    const auto& context = request.at("enemy_context");
    const auto kind = context.at("kind").get<std::string>();
    if (kind != "normal_opening" && kind != "fever_extending" && kind != "fever_turnover")
        throw std::invalid_argument("invalid conversion enemy context");
    const auto id = request.at("character").get<std::string>();
    const auto* character = dropset::find(id);
    if (!character || character->pattern.empty()) throw std::invalid_argument("unknown character or cycle");
    const u64 index = number(request, "dropset_index", 0, 15);
    const auto texts = request.at("queue").get<std::vector<std::string>>();
    if (texts.empty() || texts.size() > 12) throw std::invalid_argument("queue requires 1..12 pieces");
    fever::Queue queue;
    for (const auto& text : texts) {
        auto piece = fever::text::to_piece(text);
        auto drop = dropset::drop_at(*character, index + queue.size());
        if (!piece || !drop || !fever::text::is_matching(*piece, *drop))
            throw std::invalid_argument("piece does not match cycle");
        queue.push_back(*piece);
    }
    fever::Configs cfg;
    cfg.normal = fever::normal_scoring::find(id);
    cfg.rules.plain_pairs = cfg.rules.special_moves = true;
    cfg.rules.margin = 0;
    cfg.width = number(options, "repair_width", 1, 128);
    cfg.depth = number(options, "repair_depth", 1, 32);
    cfg.trigger = cfg.build_chain = 19;
    cfg.rebuild = true;
    cfg.hill = request.at("weights").value("hill", 0);
    const auto weights = fever::read_weights(request.at("weights"));
    auto rules = cfg.rules;
    std::vector<Node> layer{{field}}, candidates;
    int expanded = 0;
    bool cutoff = false;
    std::set<std::string> fired_boards;
    for (int depth = 0; depth < std::min(horizon, int(queue.size())) && !layer.empty(); ++depth) {
        std::vector<Node> next;
        std::set<std::string> seen;
        for (const auto& parent : layer) {
            auto moves = fever::normal_space::moves(parent.field, queue[depth], rules, depth == 0);
            for (int i = 0; i < moves.get_size(); ++i) {
                if (expanded >= max_nodes) { cutoff = true; break; }
                ++expanded;
                Node child = parent;
                auto before = child.field;
                const auto splits = split_distances(before, queue[depth], moves[i].x, moves[i].r);
                if (!child.field.drop_piece(moves[i].x, moves[i].r, queue[depth], rules)) continue;
                auto locked = child.field;
                auto masks = child.field.pop();
                const auto score = fever::normal_scoring::score(masks, *cfg.normal);
                if (child.field.is_dead(rules) || score.count > max_chain) continue;
                const auto times = attack_times(locked, masks, *std::max_element(splits.begin(), splits.end()),
                    parent.ready, request.at("timing"), request.value("pace_frames",0));
                child.ready = times.ready; child.end = times.end;
                child.path.push_back({{"x", moves[i].x}, {"r", std::string(1, fever::text::from_direction(moves[i].r))},
                    {"chain", score.count}, {"points", score.score}, {"field", fever::text::from_field(child.field)},
                    {"lock_frame",times.lock},{"attack_end",times.end}});
                beam::node::Data node{.field = child.field};
                fever::evaluate(node, weights, cfg);
                child.rank = node.score.eval;
                if (score.count) {
                    child.chain = score.count;
                    child.points = score.score;
                    child.gross = (i64(score.score) + remainder) / rate;
                    child.sent = std::max(0, child.gross - context.value("enemy_reply",0));
                    child.remaining = colored(child.field);
                    if (kind == "fever_extending" && context.value("clock_running",false)
                            && child.end >= context.at("remaining_frames").get<int>()) continue;
                    if (kind == "fever_turnover") {
                        const int end = context.at("their_end");
                        if (depth != 0 || child.end < end || child.end > end + context.at("window").get<int>()) continue;
                        if (context.value("enemy_reply",0) && request.at("gauge").get<int>()
                                + score.count * request.at("gain").get<int>() >= 7) continue;
                    }
                    if (child.sent < min_sent || child.remaining < min_material ||
                            !fever::normal_space::room(child.field, 1)) continue;
                    // The same board at different queue positions is a different continuation.
                    auto key = std::to_string(depth) + child.path.back()["field"].dump();
                    if (!fired_boards.insert(key).second) continue;
                    child.rank += child.points;
                    candidates.push_back(std::move(child));
                } else {
                    auto key = child.path.back()["field"].dump();
                    if (seen.insert(key).second) next.push_back(std::move(child));
                }
            }
            if (cutoff) break;
        }
        if (cutoff) break;
        std::stable_sort(next.begin(), next.end(), [](const Node& a, const Node& b) { return a.rank > b.rank; });
        if (next.size() > size_t(width)) next.resize(width);
        layer = std::move(next);
    }
    std::stable_sort(candidates.begin(), candidates.end(), [](const Node& a, const Node& b) {
        if (a.rank != b.rank) return a.rank > b.rank;
        return a.path.size() < b.path.size();
    });
    const int found = int(candidates.size());
    if (candidates.size() > size_t(shortlist)) candidates.resize(shortlist);
    json answer = {{"found", false}, {"expanded", expanded}, {"budget_exhausted", cutoff},
        {"candidates", found}, {"recovery_evaluated", candidates.size()}, {"searched_visible", queue.size()},
        {"enemy_context",context},{"recovery_model", "six_fixed_virtual_bags_not_an_executable_plan"}};
    i64 best = INT64_MIN;
    json diagnostics = json::array();
    for (const auto& candidate : candidates) {
        const int played = int(candidate.path.size());
        fever::Queue suffix(queue.begin() + played, queue.end());
        auto recovery = recover(candidate.field, suffix, *character, index + played, weights, cfg, min_recovery, min_safe);
        diagnostics.push_back({{"path", candidate.path}, {"viable", recovery.viable},
            {"min_chain", recovery.min_chain}, {"max_chain", recovery.max_chain}, {"repair_points", recovery.points}});
        if (!recovery.viable) continue;
        const i64 value = recovery.points + candidate.points - i64(played - 1) * 400;
        if (value <= best) continue;
        best = value;
        answer.update({{"found", true}, {"choice", candidate.path[0]}, {"path", candidate.path},
            {"conversion_chain", candidate.chain}, {"conversion_points", candidate.points}, {"sent", candidate.sent},
            {"remaining_material", candidate.remaining}, {"fire_moves", played}, {"value", value},
            {"attack_end",candidate.end},{"gross_sent",candidate.gross},
            {"repair_points", recovery.points}, {"repair_chain_min", recovery.min_chain},
            {"repair_chain_max", recovery.max_chain}, {"repair_chains", recovery.chains},
            {"repair_depths", recovery.depths}, {"next_safe_moves", recovery.next_safe}});
    }
    answer["diagnostics"] = diagnostics;
    return answer;
}
}

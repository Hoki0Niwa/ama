#include "normal_pressure.h"
#include "physics.h"
#include "../fever/normal_space.h"
#include "../fever/text.h"

namespace fever_battle {
NormalPressure::NormalPressure(const json& request, const RateSchedule& schedule, const Bonuses& bonus):
    options(request.value("normal_pressure", json::object())), rates(schedule), bonuses(bonus) {
    if (!enabled()) return;
    enemy = request.at("normal_pressure_enemy");
    timing = request.at("timing");
    available = enemy.value("available", false);
    if (!available) return;
    powers = enemy.at("powers").get<std::vector<int>>();
    if (powers.size() != 19) throw std::invalid_argument("normal pressure needs 19 enemy powers");
    for (const auto& text : enemy.at("queue")) {
        auto p = fever::text::to_piece(text.get<std::string>());
        if (!p) throw std::invalid_argument("invalid normal pressure enemy piece");
        pieces.push_back(*p);
    }
    if (pieces.empty() || pieces.size() > 3) throw std::invalid_argument("normal pressure visible queue only");
    depth = number(options.at("counter_read"), "depth", 1, 3);
    limit = number(options.at("counter_read"), "max_nodes", 1, 100000);
    auto field = fever::text::to_field(enemy.at("field").get<std::vector<std::string>>());
    if (!field) throw std::invalid_argument("invalid normal pressure enemy field");
    replies.push_back({*field});
    build(0);
}
bool NormalPressure::enabled() const {
    return options.value("pressure",json::object()).value("enabled",false)
        || options.value("finish",json::object()).value("enabled",false);
}
void NormalPressure::build(int index) {
    // Copy before growing replies: vector relocation must not invalidate this node.
    const auto node = replies[index];
    if (node.depth >= depth || node.depth >= int(pieces.size())) return;
    if (cutoff) { unread.push_back(index); return; }
    auto field = node.field;
    auto rules = rule::FEVER; rules.plain_pairs = true; rules.special_moves = true;
    auto moves = fever::normal_space::moves(field, pieces[node.depth], rules, node.depth == 0);
    std::vector<int> children;
    for (int i=0;i<moves.get_size();++i) {
        if (++expanded > limit) { cutoff = true; unread.push_back(index); break; }
        auto next = node; next.parent = index;
        const auto& move = moves[i];
        const auto splits = split_distances(next.field, pieces[node.depth], move.x, move.r);
        const int rows = *std::max_element(splits.begin(),splits.end());
        const auto table = timing.value("split_extra_frames",json::array());
        const int extra = !table.empty() && !table[rows].is_null() ? table[rows].get<int>()
            : rows * timing.at("fall_frames_per_row").get<int>();
        next.lock = node.ready + timing.at("placement_frames").get<int>() + extra;
        if (!next.field.drop_piece(move.x,move.r,pieces[node.depth],rules)) continue;
        auto locked = next.field;
        auto masks = next.field.pop();
        if (next.field.is_dead(rules)) continue;
        const auto falls = fall_features(locked,masks);
        int now = next.lock + timing.value("first_link_frames",0);
        for (int k=0;k<masks.get_size();++k) {
            const auto link = score_link(masks[k],powers[k],bonuses);
            next.links.push_back({now + timing.value("score_offset_frames",0),link.points,link.cells});
            now += link_frames(falls[k], k == masks.get_size()-1,
                timing.at("pop_frames").get<int>(),timing.at("settle_frames").get<int>());
        }
        next.ready = masks.get_size() ? now + timing.value("chain_ready_frames",0)
            : next.lock + timing.at("spawn_frames").get<int>();
        ++next.depth; next.cleared = masks.get_size() > 0;
        children.push_back(int(replies.size())); replies.push_back(std::move(next));
    }
    for (const auto child : children) build(child);
}
NormalPressure::json NormalPressure::counter(int deadline, i64 sent) const {
    const auto key = std::make_pair(deadline,sent);
    if (cache.contains(key)) return cache.at(key);
    bool complete = available;
    bool entry = available && enemy.value("gauge",0) >= 7;
    bool survives = false;
    i64 capacity = 0, full_capacity = 0, defence_1 = 0;
    int counter_cost = 1000000;
    std::vector<bool> stopped(replies.size(),false);
    for (size_t i=0;i<replies.size();++i) {
        const auto& reply = replies[i];
        if (reply.parent >= 0) {
            const auto& parent = replies[reply.parent];
            stopped[i] = stopped[reply.parent] || (parent.depth > 0 && !parent.cleared && parent.lock >= deadline);
        }
        if (stopped[i]) continue;
        const bool dropped = reply.depth > 0 && !reply.cleared && reply.lock >= deadline;
        if (!dropped && (reply.depth >= depth || reply.depth >= int(pieces.size())))
            complete = false; // A further piece could be played, but its color is unobserved/unsearched.
        i64 rest = enemy.value("remainder",i64(0)), by_deadline = 0, full = 0;
        i64 pending = sent + enemy.value("pending",i64(0));
        int gauge = enemy.value("gauge",0), cells = 0;
        for (const auto& link : reply.links) {
            const i64 total = rest + link.points;
            const int rate = rates.at(link.frame,true);
            i64 amount = total / rate; rest = total % rate;
            // Optimistically allow this packet to offset every witnessed link.
            if (pending && amount == 0) amount = 1;
            if (pending && amount > 0) gauge = std::min(7,gauge + enemy.value("gain",1));
            pending -= std::min(pending,amount);
            full += amount; cells += link.cells;
            if (link.frame <= deadline) {
                by_deadline += amount;
                if (by_deadline >= sent) counter_cost = std::min(counter_cost,cells);
            }
        }
        capacity = std::max(capacity,by_deadline); full_capacity = std::max(full_capacity,full);
        if (reply.depth <= 1) defence_1 = std::max(defence_1,by_deadline);
        entry = entry || gauge >= 7;
        // Give the defender its full chain and cleared board before the drop, even when
        // that chain ends after arrival. This makes a finish harder, never easier.
        const int drop = int(std::min<i64>(30,std::max<i64>(0,sent-full)));
        each_remainder_drop(reply.field,drop,[&](Field board) { survives = survives || !board.is_dead(rule::FEVER); });
    }
    for (const auto index : unread) {
        const auto& node = replies[index];
        if (!stopped[index] && !(node.depth > 0 && !node.cleared && node.lock >= deadline)) complete = false;
    }
    json result = {{"available",available},{"complete",complete},{"cutoff",cutoff},
        {"expanded",expanded},{"deadline",deadline},{"defence_1",defence_1},{"defence_2",capacity},
        {"full_counter",full_capacity},{"counter_cost_cells",counter_cost == 1000000 ? 0 : counter_cost},{"entry_possible",entry || (!complete && enemy.value("gain",1) > 0)},
        {"remaining",complete ? std::max<i64>(0,sent-full_capacity) : 0},
        {"finish",complete && !entry && !survives}};
    // The search contains optimistic counter paths; these are estimates, not enemy policy predictions.
    if (cache.size() < 4096) cache[key] = result;
    return result;
}
NormalPressure::json NormalPressure::rate(Field remaining, int max_chain, int redundancy,
                                        i64 sent, int deadline, bool invite) const {
    json result = {{"kind","none"},{"score",0},{"pressure",false},{"finish",false}};
    if (!enabled() || sent <= 0 || deadline < 0) return result;
    const auto reply = counter(deadline,sent);
    result["counter"] = reply;
    if (!available) { result["blocked"]="enemy_unavailable"; return result; }
    const auto& finish = options.at("finish");
    if (finish.at("enabled").get<bool>() && sent >= finish.at("min_send").get<int>() && reply.at("finish").get<bool>()) {
        result.update({{"kind","finish"},{"finish",true},{"score",finish.at("weight")}});
        return result;
    }
    const auto& cfg = options.at("pressure");
    if (!cfg.at("enabled").get<bool>()) return result;
    int colors = remaining.get_count() - remaining.data[static_cast<int>(cell::Type::GARBAGE)].get_count();
    u8 heights[6]; remaining.get_heights(heights);
    bool resources = colors >= cfg.at("min_remaining").get<int>() && redundancy <= cfg.at("max_redundancy").get<int>();
    for(int x=0;x<6;++x) resources = resources && heights[x] >= cfg.at("min_heights")[x].get<int>();
    if (!resources || max_chain > cfg.at("max_chain").get<int>()
            || sent < cfg.at("min_send").get<int>() || sent > cfg.at("max_send").get<int>()) {
        result["blocked"]="resources_or_send_range"; return result;
    }
    const auto left = reply.at("remaining").get<i64>();
    if (enemy.value("experienced",false) && enemy.value("seed_chain",19) >= cfg.at("block_seed_chain").get<int>() && (!left || reply.at("entry_possible").get<bool>())) {
        result["blocked"]="large_seed_gauge_only"; return result;
    }
    // Saturation loss is the pressure to spend normal resources on a reply, not
    // nuisance claimed to land through that reply. A witnessed counter gives evidence.
    const int cost_cells = reply.at("counter_cost_cells").get<int>();
    const bool entry = invite && reply.at("complete").get<bool>() && reply.at("entry_possible").get<bool>();
    const bool bury = left > 0 && !reply.at("entry_possible").get<bool>() && enemy.at("third_height").get<int>() + int(left/6) > cfg.at("third_column_height").get<int>();
    const i64 units = (entry ? 6 : 0) + std::min(18,cost_cells) + (bury ? std::min<i64>(30,left) : 0);
    if (units && cfg.at("weight").get<int>() > 0)
        result.update({{"kind",entry ? "invite" : bury ? "bury" : "force_counter"},
            {"pressure",true},{"score",units * cfg.at("weight").get<i64>()}});
    return result;
}
}

#include "rebuild.h"
#include "normal_space.h"

namespace fever::rebuild {
bool safe(const Field& field, const rule::Rule& rules) {
    auto copy = field;
    if (copy.is_dead(rules)) return false;
    u8 heights[6]; copy.get_heights(heights);
    return !rules.margin || !rule::is_unsafe(heights, rules);
}

Features inspect(Field field, const Queue& next, const beam::eval::Weight& w, const Configs& configs) {
    Features result;
    result.potential = fever::potential(field, w, configs);
    result.garbage = field.data[int(cell::Type::GARBAGE)].get_count();
    struct State { Field field; i32 value; };
    std::vector<State> layer{{field, 0}};
    // Only real visible pieces, no invented colors. Width 6, at most two
    // successor pieces; terminal chains are measured but never continued.
    for (size_t depth = 0; depth < std::min(size_t(2), next.size()); ++depth) {
        std::vector<State> children;
        for (const auto& parent : layer) {
            auto source = parent.field;
            auto moves = normal_space::moves(source, next[depth], configs.rules);
            for (int i = 0; i < moves.get_size(); ++i) {
                ++result.expanded;
                auto child = source;
                auto drop = child.drop_piece(moves[i].x, moves[i].r, next[depth], configs.rules);
                if (!drop) continue;
                auto masks = child.pop();
                if (!safe(child, configs.rules)) continue;
                const int links = masks.get_size();
                if (depth == 0 && links == 0 && drop->discarded == 0) ++result.safe;
                if (links > result.visible_chain) {
                    result.visible_chain = links;
                    result.visible_moves = int(depth)+1;
                }
                if (links == 0) children.push_back({child, fever::potential(child, w, configs).value});
            }
        }
        std::stable_sort(children.begin(), children.end(), [](const State& a, const State& b) { return a.value > b.value; });
        if (children.size() > 6) children.resize(6);
        layer = std::move(children);
    }
    // Readiness/space terms are small relative to a built main's real score.
    // Visible chain is bounded by the retained geometric potential: making
    // an isolated small shot does not earn a second main's future value.
    result.quality = result.potential.chain*250 - result.potential.key*100
        + std::min(24, result.safe)*20 - result.garbage*150
        + std::min(result.potential.chain, result.visible_chain)*120/std::max(1, result.visible_moves);
    return result;
}

json rank(Field field, const Queue& queue, Result& result, const beam::eval::Weight& w, const Configs& configs) {
    Queue next(queue.begin()+1, queue.begin()+std::min(queue.size(), size_t(3)));
    const auto before = inspect(field, next, w, configs);
    const int colors = field.get_count()-before.garbage;
    // A mature clean main that needs two trigger cells is still a build, not
    // an endless recovery phase. Root cleanup must not reorder it every turn.
    const bool recovering = colors <= 24 || before.garbage > 0;
    json diagnostic{{"phase", recovering ? "recover" : "build"}, {"potential_before", before.potential.chain},
                    {"key_before", before.potential.key}, {"safe_before", before.safe}, {"expanded", before.expanded}};
    if (!recovering) return diagnostic;

    struct Root { Candidate candidate; Features features; int clear; bool useful; };
    std::vector<Root> roots;
    int expanded = before.expanded;
    bool has_nonclear = false;
    for (auto candidate : result.candidates) {
        auto after = field;
        auto move = candidate.placement;
        if (!after.drop_piece(move.x, move.r, queue[0], configs.rules)) continue;
        const int links = after.pop().get_size();
        // Unfinished main protection stays with the fire policy. Do not reward
        // root moves that have already consumed >=3 links through this path.
        if (links > 2) continue;
        auto features = inspect(after, next, w, configs);
        expanded += features.expanded;
        const bool useful = links == 0 || features.potential.value > before.potential.value
            || features.garbage < before.garbage || (!configs.sustained && features.safe > before.safe);
        has_nonclear |= links == 0;
        candidate.recovery = (features.quality-before.quality)*VIRTUAL_COUNT;
        roots.push_back({candidate, features, links, useful});
    }
    if (roots.empty()) return diagnostic;
    const auto utility = [&](const Root& root) {
        // Keep the large-chain beam objective; add recovery only at the root,
        // so a cheap potential term cannot accumulate once per future move.
        return i64(root.candidate.score)+root.candidate.recovery;
    };
    std::stable_sort(roots.begin(), roots.end(), [&](const Root& a, const Root& b) {
        if (has_nonclear && a.useful != b.useful) return a.useful;
        return utility(a) > utility(b);
    });
    // Only this reconstruction set changes rank. The remaining candidates are
    // preserved so capacity/defensive consumers still have their full list.
    std::vector<Candidate> ordered;
    for (const auto& root : roots) ordered.push_back(root.candidate);
    for (const auto& candidate : result.candidates)
        if (std::none_of(ordered.begin(), ordered.end(), [&](const Candidate& c) { return c.placement == candidate.placement; }))
            ordered.push_back(candidate);
    result.candidates = std::move(ordered);
    const auto& best = roots.front();
    diagnostic.update({{"expanded", expanded}, {"potential_after", best.features.potential.chain},
        {"key_after", best.features.potential.key}, {"safe_after", best.features.safe},
        {"visible_chain", best.features.visible_chain}, {"visible_moves", best.features.visible_moves},
        {"cleanup_links", best.clear}, {"useful_cleanup", best.useful},
        {"adjustment", best.candidate.recovery/VIRTUAL_COUNT}});
    return diagnostic;
}
}

#pragma once
#include "transition.h"
#include "../ai/gaze.h"

namespace fever_battle::main_attack {
// Same quiet(8, 3) maximum-score view as main's gaze.main_q. Re-score the
// resulting board with this character's Fever-normal powers, never Tsu powers.
inline std::pair<i64, int> potential(Field field, const std::vector<int>& powers, const Bonuses& bonuses) {
    std::pair<i64, int> best{0, 0};
    dfs::quiet::search(field, 8, 3, [&](dfs::quiet::Result q) {
        auto plan = q.plan; auto masks = plan.pop(); i64 score = 0;
        for (int i = 0; i < masks.get_size(); ++i)
            score += score_link(masks[i], powers.at(std::min(i, 18)), bonuses).points;
        if (score > best.first) best = {score, masks.get_size()};
    });
    return best;
}
}

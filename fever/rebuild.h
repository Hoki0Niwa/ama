#pragma once
#include "evaluation.h"

namespace fever::rebuild {
struct Features {
    Potential potential;
    int safe = 0, visible_chain = 0, visible_moves = 0, expanded = 0;
    int garbage = 0;
    i64 quality = 0;
};
bool safe(const Field& field, const rule::Rule& rules);
Features inspect(Field field, const Queue& next, const beam::eval::Weight& w, const Configs& configs);
// No firing decision: scores surviving root moves and useful 0--2-link cleanup.
json rank(Field field, const Queue& queue, Result& result, const beam::eval::Weight& w, const Configs& configs);
}

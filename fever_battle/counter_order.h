#pragma once
#include "../core/def.h"

namespace fever_battle {
// Only compare returns already verified alive and sufficient. Excess firepower
// has no fixed "enough to fill a normal board" ceiling in a Fever battle.
inline bool prefer_full_return(i64 points, int frame, i64 other_points, int other_frame) {
    return points != other_points ? points > other_points : frame < other_frame;
}
}

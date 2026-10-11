#pragma once
#include "../core/def.h"
#include <algorithm>

namespace fever_battle {
// A settled exchange and the resources it leaves are separate from the
// physical survival of a board immediately after a clear.
struct NormalDefense {
    i64 pending = 0;
    i64 reply_exposure = 0; // next-seed estimate, not an observed delivery
    int lost_links = 0;
    bool landing_safe = true;
    bool entered = false;

    bool known_survival() const { return pending == 0 || landing_safe; }
    bool secured() const { return entered || pending == 0 || landing_safe; }
    bool can_commit() const {
        return secured() && (lost_links == 0 || entered || reply_exposure == 0);
    }
    i64 cost(i64 mainline, i64 uncountered, int reach, bool builder_fire) const {
        const double risk = entered ? 0.0 : std::min(1.0,
            double(pending + reply_exposure) / (2.0 * std::max(1, reach)));
        return lost_links * (builder_fire && can_commit() ? 0 : mainline)
            + i64(double(lost_links * uncountered) * risk);
    }
};
}

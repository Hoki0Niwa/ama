#pragma once
#include "transition.h"
#include <map>

namespace fever_battle {
// Visible normal-board counters. Unknown or truncated search never proves a finish.
class NormalPressure {
    using json = nlohmann::json;
    struct Link { int frame; i64 points; int cells; };
    struct Reply {
        Field field;
        std::vector<Link> links;
        int depth = 0, lock = 0, ready = 0, parent = -1;
        bool cleared = false;
    };
    json options, enemy, timing;
    const RateSchedule& rates;
    Bonuses bonuses;
    std::vector<int> powers;
    std::vector<piece::Piece> pieces;
    std::vector<Reply> replies;
    int expanded = 0, depth = 0, limit = 0;
    std::vector<int> unread;
    bool available = false, cutoff = false;
    i64 main_points = 0;
    int main_frame = 0;
    void build(int index);
    mutable std::map<std::pair<int,i64>, json> cache;
public:
    NormalPressure(const json& request, const RateSchedule& rates, const Bonuses& bonuses);
    bool enabled() const;
    bool allows_pending() const;
    bool preempts() const;
    i64 target_points() const { return main_points; }
    json counter(int deadline, i64 sent) const;
    json rate(Field remaining, int max_chain, int redundancy, i64 sent, int deadline, bool invite,
        int main_loss=0, int attacks=1, int consumed=0, bool quiet=true,
        i64 own_points=0, int own_frame=0) const;
};
}

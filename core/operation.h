#pragma once
#include <optional>
#include <array>
#include <vector>

// Game coordinates: y grows down, visible rows 0..11, hidden row -1.
// PAIR/TRIPLE use the first cell (pivot); QUAD/BIG use the lower-left cell.
namespace operation {
struct Pose {
    int x, y, r;
    bool armed = false;
    bool operator==(const Pose&) const = default;
};
struct Press {
    int dx, turn;
    Pose after;
    bool quick;
    int frames;
};
bool fits(const int* heights, int shape, const Pose& p);
std::optional<Pose> rotate(const int* heights, int shape, const Pose& p, int step, bool fever);
std::optional<std::vector<Press>> route(const int* heights, int shape, Pose start,
                                      int goal_x, int goal_r, bool same, bool fever, bool special = true);
std::array<std::array<bool, 4>, 6> reachable(const int* heights, int shape, Pose start, bool fever);
}

// Stable, cdecl ABI. No C++ containers cross the library boundary.
struct AmaOperationPress {
    int dx, turn, x, y, r, armed, quick, frames;
};

#pragma once
#include <optional>
#include <array>
#include <vector>

// Game coordinates: y grows down, visible rows 0..11, hidden row -1; Fever pairs also use rows -2/-3 (14th/15th).
// PAIR/TRIPLE use the first cell (pivot); QUAD/BIG use the lower-left cell.
namespace operation {
struct Pose {
    int x, y, r;
    bool armed = false;
    // Fever pair routes only: natural fall since leaving an elevated support.
    int fall_frames = 0;  // Fever pair: fraction of a row in 1/256 (see fever/operation_fall.h)
    bool operator==(const Pose&) const = default;
};
struct Press {
    int dx, turn;
    Pose after;
    bool quick;
    int frames;
};
bool fits(const int* heights, int shape, const Pose& p, bool fever = false);
std::optional<Pose> rotate(const int* heights, int shape, const Pose& p, int step, bool fever);
std::optional<std::vector<Press>> route(const int* heights, int shape, Pose start,
                                      int goal_x, int goal_r, bool same, bool fever, bool special = true);
std::array<std::array<bool, 4>, 6> reachable(const int* heights, int shape, Pose start, bool fever);

// Triple lifts from the spawn row to the 13th row are suspended (fever/operation_suspensions.h): the generic
// "push away from a blocked arm" kick offered them and the game did not make the climb. The bridge has
// measured input programs for some boards and goals which do execute; it sends their conditions with each
// request (`lift_allow`). A lift goal is offered only when it is reachable with the lifts enabled AND a
// measured case matches the board and the goal. Nothing else changes (hooks stay suspended).
struct MeasuredLift {
    int axis = -1;               // goal pivot column
    unsigned rotations = 0;      // bit r: goal rotation r accepted
    int wanted[6] = {};          // column heights the measured board had
    unsigned match = 0x3f;       // bit x: column x must equal wanted[x]
    int max_height[6] = {-1, -1, -1, -1, -1, -1};  // -1: no limit
    bool allow_full_goal = false;
};
void set_measured_lifts(std::vector<MeasuredLift> cases);
unsigned measured_lift_generation();
bool measured_lift_allowed(const int* heights, int goal_x, int goal_r);
bool has_measured_lifts();
// Enable the spawn-row lifts for this thread while a scope lives (reachability/route computed inside).
struct SpawnRowLifts {
    bool previous;
    SpawnRowLifts();
    ~SpawnRowLifts();
};
}

// Stable, cdecl ABI. No C++ containers cross the library boundary.
struct AmaOperationPress {
    int dx, turn, x, y, r, armed, quick, frames;
};

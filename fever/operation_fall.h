#pragma once
#include "../core/operation.h"
#include <algorithm>

namespace operation::fever_fall {
// Logged lateral motion advances about 1/24 row per game frame. Use the
// entered row for clearance: a fraction below row 14 cannot cross a row-13
// column. The integer ABI reports this conservative row, never rounded up
// into the clearance which has already been lost.
constexpr int frames_per_row = 24;
inline int row(const Pose& p) { return p.y + (p.fall_frames > 0); }
inline int rest(const int* h, const Pose& p) {
    constexpr int dx[] = {0, 1, 0, -1}, dy[] = {-1, 0, 1, 0};
    return std::min(11 - h[p.x], 11 - h[p.x + dx[p.r]] - dy[p.r]);
}
inline Pose advance(const int* h, Pose before, Pose after, int frames) {
    if (after.y >= -1 || after.y < before.y) {
        // Keep row-13 and ordinary routes unchanged: the game can snap a
        // fractional row-13 approach onto its support during translation.
        // This model guards only the measured row-14 clearance loss.
        // A completed lifting animation is
        // observed at its new integer height before the next input starts.
        after.fall_frames = 0;
        return after;
    }
    const int total = after.fall_frames + frames;
    after.y += total / frames_per_row;
    after.fall_frames = total % frames_per_row;
    const int floor = rest(h, after);
    if (row(after) > floor) {
        after.y = floor;
        after.fall_frames = 0;
    }
    if (after.y >= -1) after.fall_frames = 0;
    return after;
}
}

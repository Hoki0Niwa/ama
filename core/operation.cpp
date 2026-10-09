#include "operation.h"
#include <algorithm>
#include <array>
#include <limits>
#include <queue>
#include <tuple>
#include <utility>

namespace operation {
namespace {
constexpr int ox[4] = {0, 1, 0, -1}, oy[4] = {-1, 0, 1, 0};
bool occupied(const int* h, int x, int y, bool fever = false) {
    return x < 0 || x >= 6 || y < (fever ? -3 : -2) || y > 11 || y > 11 - h[x];
}
std::optional<Pose> shift(const int* h, int shape, Pose p, int dx, bool fever) {
    p.x += dx;
    return fits(h, shape, p, fever) ? std::optional(p) : std::nullopt;
}
int duration(Pose before, const Press& p, bool fever) {
    return p.turn && (p.after.x - before.x != p.dx || (fever && p.dx && p.after.y < before.y)) ? 9 : 3;
}
int index(Pose p) { return (((p.y + 3) * 6 + p.x) * 4 + p.r) * 2 + p.armed; }
constexpr int count = 15 * 6 * 4 * 2;
bool valid(const int* h, int shape, Pose p, bool fever) {
    if (!h || (shape != 2 && (!fever || (shape != 3 && shape != 4 && shape != 0)))) return false;
    if (p.x < 0 || p.x > 5 || p.y < -2 || p.y > 11 || p.r < 0 || p.r > 3) return false;
    for (int i = 0; i < 6; ++i) if (h[i] < 0 || h[i] > 14) return false;
    return true;
}
}
bool fits(const int* h, int shape, const Pose& p, bool fever) {
    if (p.y < (fever && shape == 2 ? -2 : -1)) return false;
    if (occupied(h, p.x, p.y, fever)) return false;
    if (shape == 2 || shape == 3) {
        if (occupied(h, p.x + ox[p.r], p.y + oy[p.r], fever)) return false;
        if (shape == 3 && occupied(h, p.x + ox[(p.r + 1) % 4], p.y + oy[(p.r + 1) % 4], fever)) return false;
    } else if (occupied(h, p.x, p.y - 1) || occupied(h, p.x + 1, p.y) || occupied(h, p.x + 1, p.y - 1)) {
        return false;
    }
    return true;
}
// Complete pair disposal requires the outer 13-row column's adjacent
// 12-row step. A height-only graph must not invent a flight across the board.
bool placement_allowed(const int* h, int shape, int x, int r, bool fever) {
    if (!fever || shape != 2) return true;
    const int child = x + ox[r];
    if (x < 0 || x > 5 || child < 0 || child > 5) return false;
    const bool discarded = h[x] + (r == 2) >= 13 && h[child] + (r == 0) >= 13;
    if (!discarded) return true;
    return r == 0 && ((x == 0 && h[0] == 13 && h[1] == 12) ||
                      (x == 5 && h[5] == 13 && h[4] == 12));
}
std::optional<Pose> hook(const int* h, int shape, Pose p, int dx, int step, bool fever);
std::optional<Pose> rotate(const int* h, int shape, const Pose& p, int step, bool fever) {
    if (!valid(h, shape, p, fever) || (step != 1 && step != -1)) return std::nullopt;
    // BIG changes colour in one direction. The client calibrates the other button.
    Pose direct{p.x, p.y, (p.r + (shape == 0 ? 1 : step) + 4) % 4};
    if (fits(h, shape, direct, fever)) return direct;
    if (shape == 4 || shape == 0) return std::nullopt;
    // The approach is a separate translation. Rotate while still at the
    // spawn-height window, with the upper arm over the 12th-row surface.
    const int side = shape == 3 && p.r == 2 ? 1 : step;
    const bool squeezed = shape == 2 && (p.r == 0 || p.r == 2) &&
        occupied(h, p.x - 1, p.y) && occupied(h, p.x + 1, p.y);
    if (!squeezed) if (auto q = hook(h, shape, p, side, step, fever)) return q;
    if (shape == 2) {
        // Tsu's existing push-back and two-edge quick-turn mechanics.
        // Tsu caps the pivot at row 13; Fever pairs may climb to row 14.
        if ((direct.r == 0 || direct.r == 2) && p.y < 0 && !fever) return std::nullopt;
        Pose kicked{p.x - ox[direct.r], p.y - oy[direct.r], direct.r};
        if (fits(h, shape, kicked, fever)) return kicked;
        if ((p.r == 0 || p.r == 2) && occupied(h, p.x - 1, p.y) && occupied(h, p.x + 1, p.y)) {
            if (!p.armed) return Pose{p.x, p.y, p.r, true};
            Pose flipped{p.x, p.y + (p.r == 0 ? -1 : 1), (p.r + 2) % 4};
            if (fits(h, shape, flipped, fever)) return flipped;
        }
    } else {
        // Experimental Fever triple: push away from a blocked arm by one cell.
        // This is an explicit trial model, not a verified Steam mechanic.
        for (int r : {direct.r, (direct.r + 1) % 4}) {
            if (!occupied(h, p.x + ox[r], p.y + oy[r])) continue;
            Pose kicked{p.x - ox[r], p.y - oy[r], direct.r};
            if (fits(h, shape, kicked, fever)) return kicked;
        }
    }
    return std::nullopt;
}
// Fever rotation catches the 12th-row top after the approach translation.
// It is valid only during the spawn-height window; never pre-rotate the piece.
std::optional<Pose> hook(const int* h, int shape, Pose p, int dx, int step, bool fever) {
    if (!fever || p.y != 0 || (shape != 2 && shape != 3)) return std::nullopt;
    if (shape == 2 && (p.r != 0 || step != dx)) return std::nullopt;
    // Triple asymmetry: left is CCW once; right is CCW three times (U,L,D,R).
    if (shape == 3 && (step != -1 || p.r != (dx < 0 ? 0 : 2))) return std::nullopt;
    Pose q{p.x, -1, (p.r + step + 4) % 4};
    const int arm = dx < 0 ? 3 : 1;
    const int wall = q.x + ox[arm];
    if (wall < 0 || wall > 5 || h[wall] != 12 || !fits(h, shape, q, fever)) return std::nullopt;
    return q;
}
std::array<std::array<bool, 4>, 6> reachable(const int* h, int shape, Pose start, bool fever) {
    std::array<std::array<bool, 4>, 6> result{};
    if (!valid(h, shape, start, fever) || !fits(h, shape, start, fever)) return result;
    std::array<bool, count> visited{};
    std::array<Pose, count> queue{};
    int head = 0, tail = 0;
    auto add = [&](Pose p) {
        if (visited[index(p)]) return;
        visited[index(p)] = true;
        queue[tail++] = p;
    };
    add(start);
    while (head < tail) {
        auto p = queue[head++];
        if (placement_allowed(h, shape, p.x, p.r, fever)) result[p.x][p.r] = true;
        for (int dx : {-1, 1}) {
            if (auto q = shift(h, shape, p, dx, fever)) add(*q);
        }
        for (int step : (shape == 3 && std::find(h, h + 6, 12) != h + 6 ? std::array<int, 2>{-1, 1} : std::array<int, 2>{1, -1})) {
            if (shape == 0 && step == -1) continue;
            if (auto q = rotate(h, shape, p, step, fever)) add(*q);
        }
    }
    return result;
}
std::optional<std::vector<Press>> route(const int* h, int shape, Pose start,
                                      int gx, int gr, bool same, bool fever, bool special) {
    if (!valid(h, shape, start, fever) || gx < 0 || gx > 5 || gr < 0 || gr > 3)
        return std::nullopt;
    // Tsu requires a consistent start. Fever can observe an out-of-model pose
    // while crossing a tall column: admit the observed start, validate its exits.
    if (!fever && !fits(h, shape, start, fever)) return std::nullopt;
    if (!placement_allowed(h, shape, gx, gr, fever) &&
        !(same && shape == 2 && placement_allowed(h, shape, gx + ox[gr], (gr + 2) % 4, fever)))
        return std::nullopt;
    auto goal = [&](Pose p) {
        if (!placement_allowed(h, shape, p.x, p.r, fever) || (fever && !fits(h, shape, p, fever))) return false;
        return (p.x == gx && p.r == gr) || (same && shape == 2 &&
            p.x == gx + ox[gr] && p.r == (gr + 2) % 4);
    };
    using Cost = std::tuple<int, int, int>;
    const Cost infinity{100000, 100000, 100000};
    std::array<Cost, count> costs;
    costs.fill(infinity);
    std::array<int, count> parents;
    parents.fill(-1);
    std::array<Press, count> edges{};
    using Entry = std::tuple<Cost, int, int, int, int, bool>;
    std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> heap;
    int serial = 0;
    costs[index(start)] = {0, 0, 0};
    heap.push({{0, 0, 0}, serial, start.x, start.y, start.r, start.armed});
    while (!heap.empty()) {
        auto [cost, order, x, y, r, armed] = heap.top(); heap.pop();
        Pose p{x, y, r, armed};
        if (costs[index(p)] != cost) continue;
        if (goal(p)) {
            std::vector<Press> result;
            for (int i = index(p); parents[i] != -1; i = parents[i]) result.push_back(edges[i]);
            std::reverse(result.begin(), result.end());
            return result;
        }
        auto add = [&](int dx, int turn, Pose q, bool quick) {
            Press press{dx, turn, q, quick, 0};
            press.frames = duration(p, press, fever);
            int risk = shape == 2 && (q.r == 1 || q.r == 3) ? h[q.x + ox[q.r]] : 0;
            Cost next{std::get<0>(cost) + press.frames,
                      std::get<1>(cost) + bool(dx) + bool(turn), std::get<2>(cost) + risk};
            if (costs[index(q)] <= next) return;
            costs[index(q)] = next; parents[index(q)] = index(p); edges[index(q)] = press;
            heap.push({next, ++serial, q.x, q.y, q.r, q.armed});
        };
        for (int dx : {-1, 1}) {
            if (auto q = shift(h, shape, p, dx, fever)) add(dx, 0, *q, false);
        }
        for (int step : (shape == 3 && std::find(h, h + 6, 12) != h + 6 ? std::array<int, 2>{-1, 1} : std::array<int, 2>{1, -1})) {
            if (shape == 0 && step == -1) continue;
            auto q = rotate(h, shape, p, step, fever);
            if (!q) continue;
            bool quick = q->armed || (q->r - p.r + 4) % 4 == 2;
            if (!special && (quick || q->x != p.x || q->y != p.y)) continue;
            add(0, step, *q, quick);
            if (quick || fever) continue; // Fever movement and rotation are separate edges.
            for (int dx : {-1, 1}) {
                auto a = shift(h, shape, *q, dx, fever), moved = shift(h, shape, p, dx, fever);
                auto b = moved ? rotate(h, shape, *moved, step, fever) : std::nullopt;
                if (a && b && *a == *b) add(dx, step, *a, false);
            }
        }
    }
    return std::nullopt;
}
}

#ifdef _WIN32
#define AMA_EXPORT extern "C" __declspec(dllexport)
#else
#define AMA_EXPORT extern "C"
#endif
AMA_EXPORT int ama_operation_version() { return 1; }
AMA_EXPORT int ama_operation_rule() {
#ifdef AMA_FEVER_OPERATION
    return 1;
#else
    return 0;
#endif
}
AMA_EXPORT int ama_operation_rotate(const int* h, int shape, int x, int y, int r, int armed,
                                    int step, AmaOperationPress* output) {
    if (!output) return -2;
    const auto q = operation::rotate(h, shape, {x, y, r, bool(armed)}, step, ama_operation_rule());
    if (!q) return -1;
    *output = {0, step, q->x, q->y, q->r, q->armed, q->armed || (q->r - r + 4) % 4 == 2, 3};
    return 0;
}
AMA_EXPORT int ama_operation_route(const int* h, int shape, int x, int y, int r, int armed,
                                   int gx, int gr, int same, int special, AmaOperationPress* output, int capacity) {
    const auto path = operation::route(h, shape, {x, y, r, bool(armed)}, gx, gr, bool(same), ama_operation_rule(), bool(special));
    if (!path) return -1;
    if (!output || capacity < int(path->size())) return -2;
    int i = 0;
    for (const auto& p : *path) output[i++] = {p.dx, p.turn, p.after.x, p.after.y, p.after.r,
                                            p.after.armed, p.quick, p.frames};
    return i;
}

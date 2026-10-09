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
bool occupied(const int* h, int x, int y) {
    return x < 0 || x >= 6 || y < -2 || y > 11 || y > 11 - h[x];
}
std::optional<Pose> shift(const int* h, int shape, Pose p, int dx) {
    p.x += dx;
    return fits(h, shape, p) ? std::optional(p) : std::nullopt;
}
int duration(Pose before, const Press& p) {
    return p.turn && p.after.x - before.x != p.dx ? 9 : 3;
}
int index(Pose p) { return (((p.y + 2) * 6 + p.x) * 4 + p.r) * 2 + p.armed; }
constexpr int count = 14 * 6 * 4 * 2;
bool valid(const int* h, int shape, Pose p, bool fever) {
    if (!h || (shape != 2 && (!fever || (shape != 3 && shape != 4 && shape != 0)))) return false;
    if (p.x < 0 || p.x > 5 || p.y < -2 || p.y > 11 || p.r < 0 || p.r > 3) return false;
    for (int i = 0; i < 6; ++i) if (h[i] < 0 || h[i] > 14) return false;
    return true;
}
}
bool fits(const int* h, int shape, const Pose& p) {
    if (p.y < -1) return false;
    if (occupied(h, p.x, p.y)) return false;
    if (shape == 2 || shape == 3) {
        if (occupied(h, p.x + ox[p.r], p.y + oy[p.r])) return false;
        if (shape == 3 && occupied(h, p.x + ox[(p.r + 1) % 4], p.y + oy[(p.r + 1) % 4])) return false;
    } else if (occupied(h, p.x, p.y - 1) || occupied(h, p.x + 1, p.y) || occupied(h, p.x + 1, p.y - 1)) {
        return false;
    }
    return true;
}
std::optional<Pose> rotate(const int* h, int shape, const Pose& p, int step, bool fever) {
    if (!valid(h, shape, p, fever) || (step != 1 && step != -1)) return std::nullopt;
    // BIG changes colour in one direction. The client calibrates the other button.
    Pose direct{p.x, p.y, (p.r + (shape == 0 ? 1 : step) + 4) % 4};
    if (fits(h, shape, direct)) return direct;
    if (shape == 4 || shape == 0) return std::nullopt;
    if (shape == 2) {
        // Tsu's existing push-back and two-edge quick-turn mechanics.
        // A vertical kick must not lift the pivot above the 13th row.
        if ((direct.r == 0 || direct.r == 2) && p.y < 0) return std::nullopt;
        Pose kicked{p.x - ox[direct.r], p.y - oy[direct.r], direct.r};
        if (fits(h, shape, kicked)) return kicked;
        if ((p.r == 0 || p.r == 2) && occupied(h, p.x - 1, p.y) && occupied(h, p.x + 1, p.y)) {
            if (!p.armed) return Pose{p.x, p.y, p.r, true};
            Pose flipped{p.x, p.y + (p.r == 0 ? -1 : 1), (p.r + 2) % 4};
            if (fits(h, shape, flipped)) return flipped;
        }
    } else {
        // Experimental Fever triple: push away from a blocked arm by one cell.
        // This is an explicit trial model, not a verified Steam mechanic.
        for (int r : {direct.r, (direct.r + 1) % 4}) {
            if (!occupied(h, p.x + ox[r], p.y + oy[r])) continue;
            Pose kicked{p.x - ox[r], p.y - oy[r], direct.r};
            if (fits(h, shape, kicked)) return kicked;
        }
    }
    return std::nullopt;
}
std::array<std::array<bool, 4>, 6> reachable(const int* h, int shape, Pose start, bool fever) {
    std::array<std::array<bool, 4>, 6> result{};
    if (!valid(h, shape, start, fever) || !fits(h, shape, start)) return result;
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
        result[p.x][p.r] = true;
        for (int dx : {-1, 1}) if (auto q = shift(h, shape, p, dx)) add(*q);
        for (int step : {1, -1}) {
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
    if (!fever && !fits(h, shape, start)) return std::nullopt;
    auto goal = [&](Pose p) {
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
            press.frames = duration(p, press);
            int risk = shape == 2 && (q.r == 1 || q.r == 3) ? h[q.x + ox[q.r]] : 0;
            Cost next{std::get<0>(cost) + press.frames,
                      std::get<1>(cost) + bool(dx) + bool(turn), std::get<2>(cost) + risk};
            if (costs[index(q)] <= next) return;
            costs[index(q)] = next; parents[index(q)] = index(p); edges[index(q)] = press;
            heap.push({next, ++serial, q.x, q.y, q.r, q.armed});
        };
        for (int dx : {-1, 1}) if (auto q = shift(h, shape, p, dx)) add(dx, 0, *q, false);
        for (int step : {1, -1}) {
            if (shape == 0 && step == -1) continue;
            auto q = rotate(h, shape, p, step, fever);
            if (!q) continue;
            bool quick = q->armed || (q->r - p.r + 4) % 4 == 2;
            if (!special && (quick || q->x != p.x || q->y != p.y)) continue;
            add(0, step, *q, quick);
            if (quick) continue;
            for (int dx : {-1, 1}) {
                auto a = shift(h, shape, *q, dx), moved = shift(h, shape, p, dx);
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

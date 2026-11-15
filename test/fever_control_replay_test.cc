// Recorded live pieces replayed on the port: position by frame and where they locked (doc/DISABLED_TRIPLE_OPERATIONS.md).
#include "../fever/control.h"
#include <cassert>
#include <cmath>
#include <iostream>

using Cells = std::vector<std::pair<int,int>>;
struct Seen { int frame; int rotation; float x, y; };

static int checks = 0;
static void replay(const std::array<int,6>& heights, control::Shape shape, const std::vector<uint8_t>& program,
                   const std::vector<Seen>& seen, const Cells& locked) {
    std::vector<std::string> rows(14, std::string(6, '.'));
    for (int g = 2; g <= 14; ++g) for (int x = 0; x < 6; ++x) if (14 - g < heights[size_t(x)]) rows[size_t(g - 1)][size_t(x)] = '#';
    control::Field field(rows);
    control::Rules rules; rules.pad_seat = true;
    control::Controller c(field, rules);
    control::Carry carry; carry.pad.previous = 0; c.restore(carry);
    c.spawn(shape);
    // The log's frame 0 is the first look at the piece, one control frame after it appears.
    assert(!c.step(0));
    size_t next = 0;
    for (int frame = 0; frame < 200; ++frame) {
        // A log's position is read before that frame's press has been taken.
        while (next < seen.size() && seen[next].frame == frame) {
            const auto s = c.state();
            assert(s.rotation == seen[next].rotation);
            assert(std::abs(s.fx - seen[next].x) < 0.01f && std::abs(s.fy - seen[next].y) < 0.01f);
            ++next; ++checks;
        }
        const uint8_t b = frame < int(program.size()) ? program[size_t(frame)] : uint8_t(control::DOWN);
        if (c.step(b)) {
            assert(next == seen.size());
            Cells cells; for (auto [x, y] : c.cells()) cells.push_back({x - 1, y});
            assert(cells == locked);
            ++checks;
            return;
        }
    }
    assert(false);
}

int main() {
    using namespace control;
    // 2026-10-14, the stopped "hook": J:BYB beside a 12 high column, B from the spawn pose. The route model had the
    // axis climb to the 13th row in its own column; the game pushes it one column right.
    replay({13, 12, 6, 8, 13, 12}, Shape::TRIPLE_J, {ROTATE_B, ROTATE_B, 0, 0},
           {{0, 0, 2.0f, -0.46f}, {1, 3, 2.195f, -0.42f}, {2, 3, 2.383f, -0.38f}}, {{3, 6}, {2, 6}, {3, 5}});
    // 2026-10-14, the stopped high sideways kick: J:BGB, the same push, which the route model had right.
    replay({11, 13, 8, 10, 12, 13}, Shape::TRIPLE_J, {ROTATE_B, ROTATE_B, 0, 0},
           {{0, 0, 2.0f, -0.46f}, {1, 3, 2.195f, -0.42f}, {2, 3, 2.383f, -0.38f}}, {{3, 4}, {2, 4}, {3, 3}});
    // 2026-10-30 21:41, 2P pair 30: J:BYB climbing to the right by a controller program. Every frame the log has,
    // and the 13th row lock the next board showed.
    replay({13, 12, 9, 10, 11, 12}, Shape::TRIPLE_J,
           {ROTATE_B, 0, RIGHT, 0, ROTATE_B, 0, RIGHT, 0, ROTATE_B, 0, ROTATE_B, 0},
           {{0, 0, 2.0f, -0.461f}, {1, 3, 2.195f, -0.422f}, {2, 3, 2.383f, -0.383f}, {3, 3, 3.056f, -0.344f},
            {4, 3, 4.207f, -0.305f}, {5, 2, 4.207f, -0.195f}, {6, 2, 4.207f, -0.383f}, {7, 2, 4.207f, -0.556f},
            {8, 2, 4.207f, -0.707f}, {9, 1, 4.207f, -1.0f}, {10, 1, 4.207f, -1.0f}, {11, 0, 4.207f, -1.0f}},
           {{4, 2}, {4, 1}, {5, 2}});
    std::cout << checks << " recorded positions and locks reproduced\n";
}

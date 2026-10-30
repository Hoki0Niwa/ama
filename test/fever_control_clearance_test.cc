#include "../fever/control.h"
#include <cassert>
#include <cmath>
#include <iostream>

int main() {
    int checks = 0;
    for (int height = 0; height <= 13; ++height) {
        std::vector<std::string> rows(14, std::string(6, '.'));
        for (int k = 0; k < height; ++k) rows[13-k][3] = '#';
        control::Field field(rows);
        control::Body body; body.cx = 3;
        // Include exact boundaries and the natural fall's 10/256 increments.
        for (int tick = 0; tick <= 192; ++tick) {
            const float y = -1.0f + float(tick)/64.0f;
            const int origin = int(std::floor(y - 0.25f)) + 1;
            const bool route_fits = origin <= 11-height;
            assert(route_fits == !field.ground(body, y, 1, 0));
            ++checks;
        }
        for (int tick = 0; tick <= 64; ++tick) {
            const float y = -0.5f + float(10*tick)/256.0f;
            const int origin = int(std::floor(y - 0.25f)) + 1;
            assert((origin <= 11-height) == !field.ground(body, y, 1, 0));
            ++checks;
        }
    }
    std::cout << checks << " quarter-cell clearance comparisons passed\n";
}

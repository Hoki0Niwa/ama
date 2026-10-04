#pragma once

#include "piece.h"
#include "direction.h"

namespace piece
{
struct Cell
{
    i8 x, y;
    cell::Type color;
};

struct Geometry
{
    std::array<Cell, 4> cells{};
    u8 count = 0;
    i8 pivot_x = 0, pivot_y = 0;
};

struct DropResult
{
    u8 retained = 0;  // Includes Tsu's separate row-14 occupancy, when selected.
    u8 discarded = 0;
    bool split = false;
};

// PAIR coordinates are relative to its pivot. All other shapes use the lower
// left of their 2x2 box. r is clockwise turns; BIG uses the absolute color enum
// index instead (0=RED, 1=YELLOW, 2=GREEN, 3=BLUE).
std::optional<Geometry> geometry(const Piece& value, direction::Type r);
}

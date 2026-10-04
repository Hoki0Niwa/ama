#include "piece_geometry.h"

namespace piece
{
std::optional<Geometry> geometry(const Piece& value, direction::Type r)
{
    if (!is_valid(value) || static_cast<u8>(r) >= direction::COUNT) return std::nullopt;
    Geometry result;
    result.count = u8(cell_count(value.shape));
    if (value.shape == Shape::PAIR) {
        result.cells[0] = { 0, 0, value.colors[0] };
        result.cells[1] = { direction::get_offset_x(r), direction::get_offset_y(r), value.colors[1] };
        return result;
    }
    if (value.shape == Shape::BIG) {
        for (i8 i = 0; i < 4; ++i)
            result.cells[i] = { i8(i / 2), i8(i % 2), cell::Type(static_cast<u8>(r)) };
        return result;
    }
    if (value.shape == Shape::QUAD) {
        for (i8 i = 0; i < 4; ++i) {
            i8 x = i / 2, y = i % 2;
            for (u8 turn = 0; turn < static_cast<u8>(r); ++turn) {
                const auto old_x = x;
                x = y; y = 1 - old_x;
            }
            result.cells[i] = { x, y, value.colors[i] };
        }
        return result;
    }
    // Rotate TRIPLE around its pivot, then normalize its bounding box.
    result.cells[0] = { 0, 0, value.colors[0] };
    result.cells[1] = { 0, 1, value.colors[1] };
    result.cells[2] = { 1, 0, value.colors[2] };
    i8 min_x = 0, min_y = 0;
    for (u8 i = 0; i < 3; ++i) {
        auto& c = result.cells[i];
        for (u8 turn = 0; turn < static_cast<u8>(r); ++turn) {
            const auto old_x = c.x;
            c.x = c.y; c.y = -old_x;
        }
        min_x = std::min(min_x, c.x); min_y = std::min(min_y, c.y);
    }
    for (u8 i = 0; i < 3; ++i) {
        result.cells[i].x -= min_x; result.cells[i].y -= min_y;
    }
    result.pivot_x = -min_x; result.pivot_y = -min_y;
    return result;
}
}

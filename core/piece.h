#pragma once

#include "cell.h"

namespace piece
{

enum class Shape : u8 { PAIR, TRIPLE, QUAD, BIG };

// PAIR: pivot, upper child. TRIPLE: pivot, upper arm, right arm.
// QUAD: lower left, upper left, lower right, upper right.
// BIG: colors[0] only; the other entries are NONE (four cells, one color).
struct Piece
{
    Shape shape = Shape::PAIR;
    std::array<cell::Type, 4> colors = {
        cell::Type::NONE, cell::Type::NONE, cell::Type::NONE, cell::Type::NONE
    };

    constexpr bool operator==(const Piece&) const = default;
};

constexpr usize cell_count(Shape shape)
{
    switch (shape) {
    case Shape::PAIR: return 2;
    case Shape::TRIPLE: return 3;
    case Shape::QUAD: case Shape::BIG: return 4;
    }
    return 0;
}

constexpr usize color_count(Shape shape)
{
    return shape == Shape::BIG ? 1 : cell_count(shape);
}

constexpr bool is_color(cell::Type color)
{
    return color >= cell::Type::RED && color <= cell::Type::BLUE;
}

constexpr bool is_valid(const Piece& value)
{
    const auto count = color_count(value.shape);
    if (count == 0) return false;
    for (usize i = 0; i < 4; ++i) {
        if (i < count ? !is_color(value.colors[i]) : value.colors[i] != cell::Type::NONE)
            return false;
    }
    const auto& c = value.colors;
    if (value.shape == Shape::TRIPLE) return c[0] == c[1] || c[0] == c[2];
    if (value.shape == Shape::QUAD) {
        // Two distinct colors, two adjacent cells each, including rotated forms.
        return (c[0] == c[1] && c[2] == c[3] && c[0] != c[2]) ||
               (c[0] == c[2] && c[1] == c[3] && c[0] != c[1]);
    }
    return true;
}

constexpr Piece from_pair(cell::Pair pair)
{
    return { Shape::PAIR, { pair.first, pair.second, cell::Type::NONE, cell::Type::NONE } };
}

// Special pieces and malformed data must never silently become a Tsu pair.
constexpr std::optional<cell::Pair> to_pair(const Piece& value)
{
    if (value.shape != Shape::PAIR || !is_valid(value)) return std::nullopt;
    return cell::Pair{ value.colors[0], value.colors[1] };
}

}

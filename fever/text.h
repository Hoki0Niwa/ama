#pragma once

#include "../core/core.h"
#include "../core/fever_queue.h"

// Text forms shared by the Fever engine protocol and bench_fever
namespace fever
{

namespace text
{

// "2:RG", "L:RRG", "J:RGR", "4:RRGG", "0:R"
// The colors follow piece::Piece::colors: pivot then child for a pair; pivot, upper arm, right arm
// for a triple; lower left, upper left, lower right, upper right for a quad; the one color of a big puyo.
// A triple is written L when its pivot and upper arm match (vertical, and all 3 the same), else J.
inline std::string from_piece(const piece::Piece& value)
{
    std::string result;

    switch (value.shape)
    {
    case piece::Shape::PAIR:
        result = "2:";
        break;
    case piece::Shape::TRIPLE:
        result = value.colors[0] == value.colors[1] ? "L:" : "J:";
        break;
    case piece::Shape::QUAD:
        result = "4:";
        break;
    case piece::Shape::BIG:
        result = "0:";
        break;
    }

    for (usize i = 0; i < piece::color_count(value.shape); ++i) {
        result += cell::to_char(value.colors[i]);
    }

    return result;
};

// Returns nothing for an unknown symbol, a wrong color count or colors the shape can't have
inline std::optional<piece::Piece> to_piece(const std::string& str)
{
    if (str.size() < 3 || str[1] != ':') {
        return {};
    }

    const auto drop = dropset::decode(str[0]);

    if (!drop) {
        return {};
    }

    piece::Piece result;
    result.shape = dropset::shape_of(*drop);

    if (str.size() != 2 + piece::color_count(result.shape)) {
        return {};
    }

    for (usize i = 2; i < str.size(); ++i) {
        result.colors[i - 2] = cell::from_char(str[i]);
    }

    if (!piece::is_valid(result)) {
        return {};
    }

    // L and J must agree with the colors unless all 3 are the same
    const auto& c = result.colors;

    if (*drop == dropset::Drop::TRIPLE_VERTICAL && c[0] != c[1]) {
        return {};
    }

    if (*drop == dropset::Drop::TRIPLE_HORIZONTAL && c[0] != c[2]) {
        return {};
    }

    return result;
};

// Whether the piece can be the given move of a cycle
inline bool is_matching(const piece::Piece& value, dropset::Drop drop)
{
    if (value.shape != dropset::shape_of(drop)) {
        return false;
    }

    const auto& c = value.colors;

    switch (drop)
    {
    case dropset::Drop::TRIPLE_VERTICAL:
        return c[0] == c[1];
    case dropset::Drop::TRIPLE_HORIZONTAL:
        return c[0] == c[2];
    case dropset::Drop::TRIPLE_UNKNOWN:
        return false;
    default:
        return true;
    }
};

// Field <-> 14 text rows (14th row first). Fever keeps nothing on the 14th row.
inline std::vector<std::string> from_field(Field& field)
{
    std::vector<std::string> rows = { "......" };

    for (i8 y = 12; y >= 0; --y) {
        std::string row;

        for (i8 x = 0; x < 6; ++x) {
            row += cell::to_char(field.get_cell(x, y));
        }

        rows.push_back(row);
    }

    return rows;
};

inline std::optional<Field> to_field(const std::vector<std::string>& rows)
{
    if (rows.size() != 14) {
        return {};
    }

    Field field;

    for (i8 y = 0; y < 13; ++y) {
        const auto& row = rows[13 - y];

        if (row.size() != 6) {
            return {};
        }

        for (i8 x = 0; x < 6; ++x) {
            if (row[x] == '.') {
                continue;
            }

            auto c = cell::from_char(row[x]);

            if (c == cell::Type::NONE) {
                return {};
            }

            // No floating cells
            if (y > 0 && field.get_cell(x, y - 1) == cell::Type::NONE) {
                return {};
            }

            field.set_cell(x, y, c);
        }
    }

    return field;
};

constexpr char from_direction(direction::Type r)
{
    return "URDL"[static_cast<u8>(r) & 3];
};

};

};

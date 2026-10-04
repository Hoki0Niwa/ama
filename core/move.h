#pragma once

#include "field.h"

namespace move
{

struct Placement
{
    i8 x = 0;
    direction::Type r = direction::Type::UP;
};

avec<Placement, 22> generate(Field& field, bool pair_equal);
// Special shapes use a conservative search without wall/floor kicks.
// Two-column pieces use x as their left column; PAIR retains its pivot x.
avec<Placement, 22> generate(Field& field, const piece::Piece& piece,
                            const rule::Rule& rules = rule::FEVER);

bool is_valid(u8 heights[6], u8 row14, i8 x, direction::Type r);

inline bool operator == (const Placement& a, const Placement& b)
{
    return a.x == b.x && a.r == b.r;
};

};
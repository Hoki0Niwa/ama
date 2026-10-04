#include "move.h"

namespace move
{
avec<Placement, 22> generate(Field& field, const piece::Piece& value, const rule::Rule& rules)
{
    avec<Placement, 22> result;
    if (!piece::is_valid(value) || field.is_dead(rules)) return result;
    if (value.shape == piece::Shape::PAIR) {
        // Preserve the established pair reachability, ordering and equal-color
        // deduplication. Fever does not accumulate row-14 obstruction.
        auto copy = field;
        if (rules.fever) copy.row14 = 0;
        return generate(copy, value.colors[0] == value.colors[1]);
    }
    if (!rules.fever) return result;
    u8 heights[6];
    field.get_heights(heights);
    struct Position { i8 x, y; direction::Type r; };
    bool visited[5][15][4]{};
    bool reachable[5][4]{};
    std::array<Position, 5 * 15 * 4> queue;
    usize head = 0, tail = 0;
    const auto add = [&](i8 x, i8 y, direction::Type r) {
        const auto rotation = static_cast<u8>(r);
        if (x < 0 || x > 4 || y < 0 || y > 14 || visited[x][y][rotation]) return;
        if (field.is_colliding_piece(x, y, r, value, heights, rules)) return;
        visited[x][y][rotation] = true;
        queue[tail++] = { x, y, r };
    };
    // Stage A assumption: lower-left box at columns 3-4, rows 12-13.
    const auto initial_r = value.shape == piece::Shape::BIG
        ? direction::Type(static_cast<u8>(value.colors[0])) : direction::Type::UP;
    add(2, 11, initial_r);
    while (head < tail) {
        const auto current = queue[head++];
        const auto rotation = static_cast<u8>(current.r);
        // A straight drop from every reachable pose is a candidate, even when
        // its cells later split. No sideways traversal through existing walls.
        reachable[current.x][rotation] = true;
        add(current.x - 1, current.y, current.r);
        add(current.x + 1, current.y, current.r);
        add(current.x, current.y - 1, current.r);
        const auto old = *piece::geometry(value, current.r);
        for (auto next_r : { direction::get_rotate_cw(current.r), direction::get_rotate_ccw(current.r) }) {
            const auto next = *piece::geometry(value, next_r);
            add(current.x + old.pivot_x - next.pivot_x,
                current.y + old.pivot_y - next.pivot_y, next_r);
        }
    }
    for (u8 r = 0; r < 4; ++r) for (i8 x = 0; x < 5; ++x)
        if (reachable[x][r]) result.add({ x, direction::Type(r) });
    return result;
}
}

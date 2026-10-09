#include "move.h"
#include "operation.h"

namespace move
{
avec<Placement, 22> generate(Field& field, const piece::Piece& value, const rule::Rule& rules)
{
    avec<Placement, 22> result;
    if (!piece::is_valid(value) || field.is_dead(rules)) return result;
    if (rules.fever && rules.special_moves &&
        (value.shape == piece::Shape::PAIR || value.shape == piece::Shape::TRIPLE)) {
        u8 height[6]; field.get_heights(height);
        int h[6]; for (int i = 0; i < 6; ++i) h[i] = height[i];
        const bool pair = value.shape == piece::Shape::PAIR;
        const bool same = pair && value.colors[0] == value.colors[1];
        const auto reachable = operation::reachable(h, pair ? 2 : 3, {2, 0, 0}, true);
        for (u8 r = 0; r < 4; ++r) for (i8 x = 0; x <= (pair ? 5 : 4); ++x) {
            if (same && r == 2 && reachable[x][0]) continue;
            if (same && r == 3 && x > 0 && reachable[x - 1][1]) continue;
            const auto geometry = piece::geometry(value, direction::Type(r));
            const int pivot = pair ? x : x + geometry->pivot_x;
            if (reachable[pivot][r])
                result.add({x, direction::Type(r)});
        }
        return result;
    }
    if (value.shape == piece::Shape::PAIR && !(rules.fever && rules.plain_pairs)) {
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
    // A pair's x is its pivot column (0-5), the other shapes' the left column of their box (0-4)
    const i8 x_max = value.shape == piece::Shape::PAIR ? 5 : 4;
    bool visited[6][15][4]{};
    bool reachable[6][4]{};
    std::array<Position, 6 * 15 * 4> queue;
    usize head = 0, tail = 0;
    const auto add = [&](i8 x, i8 y, direction::Type r) {
        const auto rotation = static_cast<u8>(r);
        if (x < 0 || x > x_max || y < 0 || y > 14 || visited[x][y][rotation]) return;
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
    // A pair of one color lies the same either way round: up and right stand for down and left
    const bool same = value.shape == piece::Shape::PAIR && value.colors[0] == value.colors[1];
    for (u8 r = 0; r < 4; ++r) for (i8 x = 0; x <= x_max; ++x) {
        if (!reachable[x][r]) continue;
        if (same && r == static_cast<u8>(direction::Type::DOWN) && reachable[x][static_cast<u8>(direction::Type::UP)]) continue;
        if (same && r == static_cast<u8>(direction::Type::LEFT) && x > 0
            && reachable[x - 1][static_cast<u8>(direction::Type::RIGHT)]) continue;
        result.add({ x, direction::Type(r) });
    }
    return result;
}
}

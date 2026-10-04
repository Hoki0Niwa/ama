#include "field.h"

namespace
{
struct Landing
{
    piece::Geometry geometry;
    std::array<i8, 4> final_y{};
    i8 contact_y = 0;
    bool split = false;
};

std::optional<Landing> landing(Field& field, i8 x, direction::Type r,
                               const piece::Piece& value, const rule::Rule& rules)
{
    const auto geometry = piece::geometry(value, r);
    if (!geometry || (!rules.fever && value.shape != piece::Shape::PAIR)) return std::nullopt;
    u8 heights[6];
    field.get_heights(heights);
    Landing result{ *geometry };
    std::array<i8, 6> bottoms;
    bottoms.fill(100);
    for (u8 i = 0; i < geometry->count; ++i) {
        const auto& c = geometry->cells[i];
        const int column = int(x) + c.x;
        if (column < 0 || column >= 6) return std::nullopt;
        bottoms[column] = std::min(bottoms[column], c.y);
    }
    int contact = -100, first_base = -100;
    for (i8 column = 0; column < 6; ++column) {
        if (bottoms[column] == 100) continue;
        const int base = int(heights[column]) - bottoms[column];
        contact = std::max(contact, base);
        if (first_base == -100) first_base = base;
        else if (base != first_base) result.split = true;
    }
    result.contact_y = i8(contact);
    for (u8 i = 0; i < geometry->count; ++i) {
        const auto& c = geometry->cells[i];
        const int column = int(x) + c.x;
        int below = 0;
        for (u8 j = 0; j < geometry->count; ++j)
            below += geometry->cells[j].x == c.x && geometry->cells[j].y < c.y;
        result.final_y[i] = i8(heights[column] + below);
        // Only the 14th and 15th rows are modelled as active space in Fever.
        if (contact + c.y > 14) return std::nullopt;
    }
    if (!rules.fever) {
        if (result.final_y[0] > 12 || result.final_y[1] > 13) return std::nullopt;
        if (result.final_y[1] == 13 && (field.row14 & (1 << (x + geometry->cells[1].x))))
            return std::nullopt;
    }
    return result;
}
}

bool Field::is_dead(const rule::Rule& rules)
{
    // Retain the exact old Tsu height criterion, even for fields with gaps.
    if (rules.death_columns == rule::TSU.death_columns) return get_height(2) > 11;
    u8 heights[6];
    get_heights(heights);
    return rule::is_dead(heights, rules);
}

bool Field::is_colliding_piece(i8 x, i8 y, direction::Type r, const piece::Piece& value,
                               const rule::Rule& rules)
{
    u8 heights[6];
    get_heights(heights);
    return is_colliding_piece(x, y, r, value, heights, rules);
}

bool Field::is_colliding_piece(i8 x, i8 y, direction::Type r, const piece::Piece& value,
                               u8 heights[6], const rule::Rule& rules)
{
    const auto geometry = piece::geometry(value, r);
    if (!geometry || (!rules.fever && value.shape != piece::Shape::PAIR)) return true;
    if (!rules.fever) return is_colliding_pair(x, y, r, heights);
    for (u8 i = 0; i < geometry->count; ++i) {
        const auto& c = geometry->cells[i];
        const int cx = int(x) + c.x, cy = int(y) + c.y;
        if (cx < 0 || cx >= 6 || cy < 0 || cy > 14) return true;
        if (cy < heights[cx]) return true;
    }
    // Fever has no retained row-14 occupancy. Legacy field.row14 is ignored.
    return false;
}

std::optional<u8> Field::get_drop_piece_frame(i8 x, direction::Type r, const piece::Piece& value,
                                             const rule::Rule& rules)
{
    const auto plan = landing(*this, x, r, value, rules);
    if (!plan) return std::nullopt;
    // Same abstract 1/2 cost as Tsu, not measured game frames (stage B).
    return u8(1 + plan->split);
}

std::optional<piece::DropResult> Field::drop_piece(i8 x, direction::Type r, const piece::Piece& value,
                                                 const rule::Rule& rules)
{
    const auto plan = landing(*this, x, r, value, rules);
    if (!plan) return std::nullopt;
    piece::DropResult result{ 0, 0, plan->split };
    if (!rules.fever) {
        drop_pair(x, r, *piece::to_pair(value));
        result.retained = 2;
        return result;
    }
    // Sort by local row so each column's vertical color order survives splitting.
    std::array<u8, 4> order{ 0, 1, 2, 3 };
    for (u8 i = 1; i < plan->geometry.count; ++i) for (u8 j = i; j > 0; --j) {
        if (plan->geometry.cells[order[j - 1]].y <= plan->geometry.cells[order[j]].y) break;
        std::swap(order[j - 1], order[j]);
    }
    u8 heights[6];
    get_heights(heights);
    for (u8 k = 0; k < plan->geometry.count; ++k) {
        const auto i = order[k];
        const auto& c = plan->geometry.cells[i];
        const i8 column = x + c.x;
        const int overflow_y = rules.overflow == rule::Overflow::ON_CONTACT
            ? plan->contact_y + c.y : plan->final_y[i];
        if (overflow_y >= 13) {
            ++result.discarded;
            continue;
        }
        set_cell(column, heights[column]++, c.color);
        ++result.retained;
    }
    row14 = 0;
    return result;
}

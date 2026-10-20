#pragma once
#include <bit>
#include "../core/core.h"
#include "../lib/nlohmann/json.hpp"
#include "timing.h"

namespace fever_battle {
inline std::vector<int> split_distances(Field& field, const piece::Piece& piece,
                                       int x, direction::Type direction) {
    auto geometry = piece::geometry(piece, direction);
    std::array<int, 6> support; support.fill(-100);
    int anchor = -100;
    for (int i = 0; i < geometry->count; ++i) {
        const auto cell = geometry->cells[i];
        int column = x + cell.x;
        support[column] = std::max(support[column], int(field.get_height(column)) - cell.y);
        anchor = std::max(anchor, support[column]);
    }
    std::vector<int> result;
    for (int x = 0; x < 6; ++x)
        if (support[x] != -100) result.push_back(anchor - support[x]);
    return result;
}
inline nlohmann::json fall_features(Field field, avec<Field, 19>& pops) {
    auto result = nlohmann::json::array();
    for (int i = 0; i < pops.get_size(); ++i) {
        auto mask = pops[i].get_mask();
        mask = mask | (mask.get_expand() & field.data[static_cast<int>(cell::Type::GARBAGE)]);
        int moving = 0, distance_sum = 0, max_fall = 0, columns = 0;
        auto moving_distances = nlohmann::json::array();
        for (int x = 0; x < 6; ++x) {
            int holes = 0; bool moved = false;
            auto distances = nlohmann::json::array();
            for (int y = 0; y < 13; ++y) {
                if (mask.get_bit(x, y)) ++holes;
                else if (holes && field.is_occupied(x, y)) {
                    ++moving; distance_sum += holes;
                    max_fall = std::max(max_fall, holes); moved = true;
                    distances.push_back(holes);
                }
            }
            columns += moved;
            moving_distances.push_back(distances);
        }
        result.push_back({{"moving_puyos", moving}, {"distance_sum", distance_sum},
                          {"max_fall", max_fall}, {"moving_columns", columns},
                          {"moving_distances_by_column", moving_distances},
                          {"cleared_including_garbage", mask.get_count()}});
        for (int c = 0; c < cell::COUNT; ++c) field.data[c].pop(mask);
    }
    return result;
}
// contact_frames of each link, as from fall_features, without building its JSON:
// a search asks this for every line it weighs.
// The contact frames of each link into `out` (as many as `pops`), without allocating.
inline void contact_frames_by_link(Field field, avec<Field, 19>& pops, int out[19]) {
    for (int i = 0; i < pops.get_size(); ++i) {
        auto mask = pops[i].get_mask();
        mask = mask | (mask.get_expand() & field.data[static_cast<int>(cell::Type::GARBAGE)]);
        int frames = 0;
        for (int x = 0; x < 6; ++x) {
            // Rows 0..12 of the column: the popped cells (holes), and the cells above the lowest hole that
            // fall (movers). The farthest a mover falls is the holes below the highest of them.
            const unsigned holes = mask.get_col(i8(x)) & 0x1FFFu;
            if (!holes) continue;
            const unsigned lowest = holes & (0u - holes);
            // Field::is_occupied: below the column's height.
            const unsigned occupied = ((1u << field.get_height(i8(x))) - 1) & 0x1FFFu;
            const unsigned movers = occupied & ~holes & ~((lowest << 1) - 1);
            if (!movers) continue;
            const int moved = std::popcount(movers);
            const unsigned top = 1u << (std::bit_width(movers) - 1);
            const int distance = std::popcount(holes & (top - 1));
            frames = std::max(frames, column_contact_frames(distance, moved - 1));
        }
        out[i] = frames;
        for (int c = 0; c < cell::COUNT; ++c) field.data[c].pop(mask);
    }
}
inline std::vector<int> contact_frames_by_link(Field field, avec<Field, 19>& pops) {
    int frames[19];
    contact_frames_by_link(field, pops, frames);
    return std::vector<int>(frames, frames + pops.get_size());
}
// Exact board geometry per link; temporal constants are supplied separately.
inline std::vector<int> fall_distances(Field field, avec<Field, 19>& pops) {
    std::vector<int> result;
    for (int i = 0; i < pops.get_size(); ++i) {
        auto mask = pops[i].get_mask();
        mask = mask | (mask.get_expand() & field.data[static_cast<int>(cell::Type::GARBAGE)]);
        int max_fall = 0;
        for (int x = 0; x < 6; ++x) {
            int holes = 0;
            for (int y = 0; y < 13; ++y) {
                if (mask.get_bit(x, y)) ++holes;
                else if (field.is_occupied(x, y)) max_fall = std::max(max_fall, holes);
            }
        }
        result.push_back(max_fall);
        for (int c = 0; c < cell::COUNT; ++c) field.data[c].pop(mask);
    }
    return result;
}
}

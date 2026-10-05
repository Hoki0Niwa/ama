#pragma once
#include "../core/core.h"
#include "../lib/nlohmann/json.hpp"

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

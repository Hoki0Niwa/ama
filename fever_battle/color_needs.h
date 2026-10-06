#pragma once
#include "../core/core.h"
#include "../lib/nlohmann/json.hpp"

namespace fever_battle {
struct ColorPort { int color, x, y, needed, chain; };
struct ColorNeeds {
    int chain = 0;
    std::array<int, 4> reserve{};
    std::vector<ColorPort> ports;
    int quality(const std::vector<piece::Piece>& queue, size_t start) const;
    nlohmann::json describe(const std::vector<piece::Piece>& queue, size_t start) const;
};
ColorNeeds color_needs(Field field);
nlohmann::json normal_colors(Field field, const nlohmann::json& request);
}

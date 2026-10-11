#pragma once
#include "normal_scoring_data.h"
#include "../core/core.h"
#include <stdexcept>

namespace fever::normal_scoring {
inline const Entry* find(std::string_view id) {
    for (const auto& e : ENTRIES) if (e.id == id) return &e;
    throw std::invalid_argument("missing Fever-normal scoring table");
}

// Count colored cells only: adjacent nuisance vanishes but earns no points.
inline chain::Score score(avec<Field, 19>& masks, const Entry& entry) {
    chain::Score result{masks.get_size(), 0};
    for (int i = 0; i < masks.get_size(); ++i) {
        auto mask = masks[i];
        int colors = 0, cells = 0, groups = 0;
        for (int c = 0; c < cell::COUNT-1; ++c) {
            if (mask.data[c].is_empty()) continue;
            ++colors;
            while (!mask.data[c].is_empty()) {
                auto group = mask.data[c].get_mask_group_lsb();
                int n = group.get_count(); cells += n; groups += GROUP[std::min(n, 11)];
                mask.data[c] = mask.data[c] & ~group;
            }
        }
        result.score += 10*cells*std::clamp(entry.powers[i]+groups+COLOR[colors], MINIMUM, MAXIMUM);
    }
    return result;
}

inline int pure(int count, const Entry& e) {
    int score = 0;
    for (int i = 0; i < count; ++i) score += 40*std::clamp(e.powers[i], MINIMUM, MAXIMUM);
    return score;
}
inline int excess_cells(avec<Field, 19>& masks) {
    const int count = masks.get_size();
    if (count < 2) return 0;
    int excess = 0;
    for (int i = 1; i < count; ++i) {
        int cells = 0;
        for (int c = 0; c < cell::COUNT-1; ++c) cells += masks[i].data[c].get_count();
        excess += std::max(0, cells-6);
    }
    return excess;
}
}

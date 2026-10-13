#pragma once
#include "normal_scoring_data.h"
#include "../core/core.h"
#include <map>
#include <span>
#include <stdexcept>
#include <string>

namespace fever::normal_scoring {
// Modified chain power tables of a game (ppmod bonus_normal_N). std::map nodes keep their address,
// so a pointer from find() sees later overrides; set between requests.
inline std::map<std::string, Entry, std::less<>>& overlay() {
    static std::map<std::string, Entry, std::less<>> table;
    return table;
}
// powers: the first 19 links of the game's table; empty restores the compiled-in table.
inline bool set_override(std::string_view id, std::span<const int> powers) {
    const Entry* base = nullptr;
    for (const auto& e : ENTRIES) if (e.id == id) { base = &e; break; }
    if (base == nullptr) return false;
    Entry custom = *base;
    if (!powers.empty()) {
        if (powers.size() != custom.powers.size()) return false;
        for (size_t i = 0; i < powers.size(); ++i) {
            if (powers[i] < 0 || powers[i] > MAXIMUM) return false;
            custom.powers[i] = powers[i];
        }
    }
    overlay().insert_or_assign(std::string(id), custom);
    return true;
}
inline void clear_overrides() {
    for (auto& [id, entry] : overlay())
        for (const auto& e : ENTRIES) if (e.id == id) entry = e;
}

inline const Entry* find(std::string_view id) {
    if (const auto it = overlay().find(id); it != overlay().end()) return &it->second;
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

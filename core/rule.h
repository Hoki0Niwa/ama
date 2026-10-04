#pragma once

#include "def.h"

namespace rule
{
// Fever's row-14 disappearance is confirmed by the user. Its timing relative
// to splitting is unverified; both models are explicit until machine testing.
enum class Overflow : u8 { TSU_ROW14, AFTER_SPLIT, ON_CONTACT };

struct Rule
{
    bool fever;
    u8 death_columns;
    Overflow overflow;
};

inline constexpr Rule TSU{ false, 0b000100, Overflow::TSU_ROW14 };
inline constexpr Rule FEVER{ true, 0b001100, Overflow::AFTER_SPLIT };
inline constexpr Rule FEVER_CONTACT{ true, 0b001100, Overflow::ON_CONTACT };

// Height is measured from the floor; the 12th row ends the game after pop.
inline bool is_dead(const u8 heights[6], const Rule& rules)
{
    for (i8 x = 0; x < 6; ++x)
        if ((rules.death_columns & (1 << x)) && heights[x] > 11) return true;
    return false;
}
}

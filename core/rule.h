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
    // Fever only: pairs are offered like the other shapes, without kicks or climbing over a column that
    // is as high as the spawn row. Such placements exist but need frame-exact inputs on the real game.
    bool plain_pairs = false;
    // main-based operations plus Fever spawn hooks and pair offscreen climbing.
    bool special_moves = false;
    // Fever search only: rows kept free below the 12th in the death columns. The search then never leaves
    // those columns higher than 11 - margin after a move, so that a piece that goes wrong on the real game
    // does not end the match at once. The rule itself (is_dead) is unchanged.
    u8 margin = 0;
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

// Alive, but higher in a death column than the search is asked to go (Rule::margin).
inline bool is_unsafe(const u8 heights[6], const Rule& rules)
{
    if (rules.margin == 0) return false;
    for (i8 x = 0; x < 6; ++x)
        if ((rules.death_columns & (1 << x)) && heights[x] + rules.margin > 11) return true;
    return false;
}
}

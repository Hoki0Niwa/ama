#pragma once

#include "search.h"

// Fever counterpart of ai::fire, with the trigger given as a chain length
namespace fever
{

namespace fire
{

// Field count from which any chain in hand is fired rather than risking death
constexpr i32 PANIC_COUNT = 74;
constexpr i32 PANIC_CHAIN = 7;

struct Decision
{
    move::Placement placement = move::Placement();
    chain::Score chain = { 0, 0 };
};

// Longest chain the piece triggers right away, ties broken by score
std::optional<Decision> best_now(
    Field field,
    const piece::Piece& piece,
    const rule::Rule& rules = rule::FEVER
);

// Returns the placement to play instead of the search's first candidate, if the policy takes over
std::optional<Decision> decide(
    Field field,
    const piece::Piece& piece,
    const Result& search,
    i32 trigger,
    const rule::Rule& rules = rule::FEVER
);

};

// One move of solo play, shared by the engine and bench_fever
struct Choice
{
    move::Placement placement = move::Placement();
    i32 chain = 0;    // Longest chain the search expects, or the chain fired now
    size_t score = 0; // Average chain score over the virtual queues, or the score fired now
    bool fire = false;
};

// `queue` holds the visible pieces only; queue[0] is move `index` of the character's cycle
std::optional<Choice> think(
    Field field,
    const Queue& queue,
    const dropset::Character& character,
    u64 index,
    const beam::eval::Weight& w,
    Configs configs = Configs()
);

};

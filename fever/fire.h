#pragma once

#include "search.h"

// Fever counterpart of ai::fire, with the trigger given as a chain length
//
// ai::fire only looks at the chain the pair in hand triggers. Here the policy looks at every chain
// the visible pieces can trigger, which is exact: their colors are known. The search itself scores
// a placement on the virtual queues, which bring every color within 2 pieces, so on a crowded field
// it keeps expecting a chain that the real pieces never trigger and shaves the field with small
// chains instead. Committing to a chain as soon as the visible pieces reach it avoids that.
namespace fever
{

namespace fire
{

// Pieces the fire policy looks through: the piece in hand, NEXT and NEXT2
constexpr size_t VISIBLE = 3;

struct Decision
{
    move::Placement placement = move::Placement(); // The first placement towards the chain
    chain::Score chain = { 0, 0 };
    i32 moves = 0; // Pieces needed to trigger it, 1 when the piece in hand does
};

// Longest chain the piece triggers right away, ties broken by score
std::optional<Decision> best_now(
    Field field,
    const piece::Piece& piece,
    const rule::Rule& rules = rule::FEVER
);

// Longest chain the visible pieces trigger, ties broken by fewer moves then by score
// Nothing if no placement survives
std::optional<Decision> best_visible(
    Field field,
    const Queue& queue,
    const rule::Rule& rules = rule::FEVER
);

// Chain length worth firing on a field with that many cells
i32 get_required(i32 count, const Configs& configs);

// Returns the placement to play instead of the search's first candidate, if the policy takes over:
// - a chain worth the trigger is within the visible pieces
// - the field is about to overflow and a chain worth panic_chain is within the visible pieces
// - the search is about to shave the field with a small chain while a chain worth shave_chain is
//   within the visible pieces
std::optional<Decision> decide(
    Field field,
    const Queue& queue,
    const Result& search,
    const Configs& configs
);

};

// One move of solo play, shared by the engine and bench_fever
struct Choice
{
    move::Placement placement = move::Placement();
    i32 chain = 0;    // Longest chain the search expects, or the chain being fired
    size_t score = 0; // Average chain score over the virtual queues, or the score being fired
    bool fire = false;
    i32 fire_moves = 0; // Pieces until the chain being fired pops, 1 when this placement pops it
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

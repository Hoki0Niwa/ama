#pragma once

#include "search/search.h"

namespace ai
{

// Fire policy on top of the beam search
//
// The beam search scores a placement by the biggest chain it can reach within its depth on a few
// sampled queues, which is optimistic when the field is nearly full: the sampled queues always bring
// every color within 2 pairs, the real one doesn't. Left alone, the search sometimes keeps stretching
// until no placement is left and dies waiting for a color.
// This policy takes over in 2 cases only:
// - fires right away when a chain worth the trigger is in hand
// - fires whatever chain is in hand when the field is about to overflow
// Finer rules (firing when the next move would shrink the chain that one color triggers, keeping the
// chain fireable with the next visible pairs) were tried and lost about 15,000 points per game: the
// beam's rebuilds of the chain head look like a loss to such a rule but pay off a few moves later.
namespace fire
{

// Field count from which any chain in hand is fired rather than risking death
constexpr i32 PANIC_COUNT = 74;
constexpr i32 PANIC_SCORE = 10000;

struct Decision
{
    move::Placement placement = move::Placement();
    i32 eval = 0;
};

// Returns the placement to play instead of the beam's first candidate, if the policy takes over
std::optional<Decision> decide(
    Field field,
    const cell::Queue& queue,
    const beam::Result& beam,
    i32 trigger
);

};

};

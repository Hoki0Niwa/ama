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
// This policy takes over in these cases only:
// - fires right away when a chain worth the trigger is in hand
// - fires whatever chain is in hand when the field is about to overflow
// - when the field is about to overflow with nothing worth firing in hand (the trigger got covered),
//   plays the beam candidate that leaves the biggest chain fireable with the next pair
// - optionally (Policy::guard, off by default), late in the build, plays the first beam candidate that
//   keeps the chain in hand fireable with the next pair
// Finer rules applied over the whole game (firing when the next move would shrink the chain that one
// color triggers, keeping the chain fireable with the next visible pairs) were tried and lost about
// 15,000 points per game: the beam's rebuilds of the chain head look like a loss to such a rule but
// pay off a few moves later. The guard limited to the last phase of the build lost as well (see
// Policy and docs/challenge-150k.md), so it is kept only for experiments.
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

// Late-game parameters (see decide)
struct Policy
{
    // Field count from which any chain in hand is fired rather than risking death
    i32 panic_count = PANIC_COUNT;
    // Keeps the chain in hand fireable once the field holds this many puyos
    // Off by default: on the 1P benchmark the guard fired 100,000-130,000 chains 2-6 moves early in
    // about a third of the games (10,000-20,000 points each) and did not rescue the games that ended
    // without a chain, which were lost to a walled-off trigger rather than a covered one
    bool guard = false;
    // Whether the guard fires the chain when no candidate keeps it; off, it only reorders candidates
    bool guard_fire = false;
    i32 guard_count = 66;
    // The guard only protects a chain worth at least this much
    i32 guard_score = 100000;
    // The guard only steps in when the beam's choice leaves less than this percentage of the chain
    // fireable with the next pair: a rebuild of the chain head keeps most of it, covering the trigger
    // keeps almost nothing
    i32 guard_keep = 50;
};

// Returns the placement to play instead of the beam's first candidate, if the policy takes over
std::optional<Decision> decide(
    Field field,
    const cell::Queue& queue,
    const beam::Result& beam,
    i32 trigger,
    const Policy& policy = Policy()
);

};

};

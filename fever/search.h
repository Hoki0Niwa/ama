#pragma once

#include "../ai/search/beam/beam.h"
#include "../core/fever_queue.h"

// Fever counterpart of ai/search/beam: the same layers, table and evaluation,
// expanded with piece::Piece placements under rule::FEVER.
// Stage A measures chains by their length. The candidates still carry the Tsu
// point score to order placements, because the per-character power tables are
// not transcribed yet (stage B).
namespace fever
{

// Children that already popped a chain this long aren't searched further
constexpr i32 PRUNE_CHAIN = 5;

struct Configs
{
    size_t width = 250;
    size_t depth = 16;
    i32 trigger = 13; // Chain length that ends the search early
    bool stretch = true;
    rule::Rule rules = rule::FEVER;
};

struct Candidate
{
    move::Placement placement = move::Placement();
    size_t score = 0; // Biggest chain score found, summed over the virtual queues
    i32 chain = 0;    // Longest chain found on any virtual queue
};

struct Result
{
    std::vector<Candidate> candidates = {};
};

void expand(
    const piece::Piece& piece,
    beam::node::Data& node,
    const beam::eval::Weight& w,
    const rule::Rule& rules,
    std::function<void(beam::node::Data&, const move::Placement&, const chain::Score&)> callback
);

// Beam search over a fully known queue
Result search(
    Field field,
    const Queue& queue,
    const beam::eval::Weight& w,
    Configs configs = Configs()
);

// `queue` holds the visible pieces only; queue[0] is move `index` of the
// character's cycle. The rest of the depth is filled with the virtual queues.
Result search_multi(
    Field field,
    const Queue& queue,
    const dropset::Character& character,
    u64 index,
    const beam::eval::Weight& w,
    Configs configs = Configs()
);

};

#pragma once

#include "../ai/search/beam/beam.h"
#include "../core/fever_queue.h"
#include "stock.h"
#include "normal_scoring.h"

// Fever counterpart of ai/search/beam: the same layers, table and evaluation,
// expanded with piece::Piece placements under rule::FEVER.
// Construction uses the character's normal-board scoring, not seed-mode powers.
namespace fever
{

// Children that already popped a chain this long aren't searched further
constexpr i32 PRUNE_CHAIN = 5;

struct Configs
{
    bool construction_scoring = true;
    const normal_scoring::Entry* normal = nullptr;
    bool rebuild = false; // Observed opening completed; enables root recovery evaluation.
    size_t width = 250;
    size_t depth = 16;
    i32 trigger = 14; // Chain length that ends the search early and that is fired
    i32 build_chain = 0; // Optional construction target, independent of the fire policy
    bool preserve_build = false; // Avoid incidental clears when a nonclearing root survives
    bool stretch = true;
    // Field count from which any chain within the visible pieces is fired rather than risking death,
    // and the shortest chain worth firing that way
    i32 panic_count = 70;
    i32 panic_chain = 11;
    // Cells per link by which that chain length slides: the fuller the field, the shorter the chain
    // accepted, and below panic_count it rises by one link per step up to the trigger. 0 disables.
    i32 panic_step = 0;
    // When the search's own move would pop a shorter chain than this while the visible pieces
    // trigger one at least this long, that chain is fired instead of shaving the field. 0 disables.
    i32 shave_chain = 0;
    // The number of pieces placed so far in the game, and the number from which the chain length that
    // is fired falls by one link every patience_step pieces (a field that keeps being shaved by small
    // chains otherwise never fires). 0 disables.
    i32 moves = 0;
    i32 patience = 0;
    i32 patience_step = 3;
    rule::Rule rules = rule::FEVER;
    // Fever-only shape weight (key "hill" of the fever weight set). The shared terms only see single
    // columns lower (well) or higher (bump) than both their neighbours.
    // hill: eval points per row by which a column stands above the lowest column on its left and the
    //       lowest on its right, whichever of the two is higher. Zero for a field that only goes down
    //       toward one place: a valley (both ends high) or a wedge (one end high). Such a field keeps a way
    //       open from where the pieces appear to every column.
    i32 hill = 0;
    // Per occupied cell in columns 2/5, counted on the board after clearing.
    i32 upper_12 = 0;
    i32 upper_13 = 0;
    // Penalize an early row-13 wall only while column 1 still has this much room.
    i32 upper_13_left_max = 9;
    // Fever-only weights of the offset stock (keys "stock" and "stock_color", see fever/stock.h):
    // eval points per weighted link the board can pop without a quiet placement, up to stock_want
    // links (7 minus the gauge), and per color that fires something with one puyo.
    i32 stock = 0;
    i32 stock_color = 0;
    i32 stock_want = 7;
    // Chooses the placement by the best evaluation its deepest positions reach, not by the biggest
    // chain found below it. A build that aims at offsets has no chain score to be ranked by.
    bool aim = false;
    bool sustained = false;
    int pace_frames = 55;
    int elapsed_build_frames = 0;
    int sustained_min_chain = 13;
};

// Parse shared weights without requiring or accepting Tsu's retained row-14 term.
inline beam::eval::Weight read_weights(json set)
{
    set["waste_14"] = 0;
    return set.get<beam::eval::Weight>();
}

inline void read_upper_weights(Configs& configs, const json& set)
{
    configs.upper_12 = 0;
    configs.upper_13 = 0; // User disabled the legacy terms, including launcher snapshots.

}

// Estimated cycle rate for virtual construction; never a proof that unknown colors fire.
inline i64 cycle_rate(const chain::Score& chain, int moves, const Configs& cfg) {
    if (chain.count < cfg.sustained_min_chain) return 0;
    const i64 frames = cfg.elapsed_build_frames + i64(moves)*cfg.pace_frames
        + 24 + i64(chain.count)*69;
    return i64(chain.score)*60000/std::max<i64>(1,frames);
}

// Rows by which the four inner columns stand above the lowest column on either side of them.
inline i32 get_hill(const u8 heights[6])
{
    i32 result = 0;
    for (i32 x = 1; x < 5; ++x) {
        i32 left = 99, right = 99;
        for (i32 i = 0; i < x; ++i) left = std::min(left, i32(heights[i]));
        for (i32 i = x + 1; i < 6; ++i) right = std::min(right, i32(heights[i]));
        result += std::max(0, i32(heights[x]) - std::max(left, right));
    }
    return result;
}

// The board's evaluation: the shared one plus what only this rule has.
void evaluate_normal(beam::node::Data& node, const beam::eval::Weight& w, const Configs& configs);

inline void evaluate(beam::node::Data& node, const beam::eval::Weight& w, const Configs& configs)
{
    auto shared = w;
    shared.waste_14 = 0;
    if (configs.normal) evaluate_normal(node, shared, configs);
    else beam::eval::evaluate(node, shared);
    if (configs.hill != 0) {
        u8 heights[6];
        node.field.get_heights(heights);
        node.score.eval += get_hill(heights) * configs.hill;
    }
    if (configs.stock != 0 || configs.stock_color != 0) {
        auto stock = stock::evaluate(node.field, configs.stock_want);
        node.score.eval += stock.units * configs.stock + stock.colors * configs.stock_color;
    }
}

struct Candidate
{
    move::Placement placement = move::Placement();
    size_t score = 0; // Biggest chain score found, summed over the virtual queues
    i32 chain = 0;    // Longest chain found on any virtual queue
    // With Configs::aim: the best evaluation among the deepest positions searched below this
    // placement, summed over the virtual queues
    i64 aim = 0;
    int next_room = 1;
    i64 throughput = 0;
    i64 recovery = 0; // Root-only reconstruction adjustment in score units.
};

// What a placement is worth under Configs::aim once the beam has dropped every position below it:
// less than any evaluation, and less the sooner it happened
constexpr i64 AIM_LOST = -1000000000000;

struct Result
{
    std::vector<Candidate> candidates = {};
    i32 completed_depth = 0;
    std::vector<i32> virtual_depths = {};
};

void expand(
    const piece::Piece& piece,
    beam::node::Data& node,
    const beam::eval::Weight& w,
    const rule::Rule& rules,
    std::function<void(beam::node::Data&, const move::Placement&, const chain::Score&)> callback,
    const normal_scoring::Entry* normal = nullptr
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

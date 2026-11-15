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
    int side_frontier_slots = 0; // Reserve within width, never expand an extra layer.
    bool construction_scoring = true;
    bool maximize_score = false;
    bool score_rebuild = false;
    bool score_repair = false;
    bool score_repair_damaged = false;
    bool score_preserve_main = false;
    // Rank a one- or two-link root clear that keeps an 8+ link main (held_main within one link) with the
    // non-clearing builds, by score. Without it every clearing root ranks below every quiet root.
    bool score_keep_main_clear = false;
    // The opening also keeps an 8+ link main as Configs::score_preserve_main keeps the second: a build that
    // loses three links or more is replaced by the best root that keeps it, unless that build beats the keeper
    // on every virtual queue and by this percentage of the summed score (0: never).
    bool score_retain_main = false;
    int score_retain_override_percent = 150;
    bool preserve_visible_fire = false; // Follow through on a reachable main after a clear.
    u32 root_placements = 0xffffffu;
    int score_opening_min_chain = 0; // Below this length, keep building while space permits.
    // Under Configs::maximize_score: the character's standard chain whose points are the fire line, and
    // the shortest visible chain whose route is kept once it reaches its own standard points.
    int score_fire_chain = 14;
    int score_reserve_chain = 12;
    // Below score_opening_min_chain, a visible chain this long keeps its route while the opening builds on,
    // and is fired where no build keeps it (0: one link short of score_fire_chain).
    int score_keep_fallback_chain = 0;
    int virtual_colors = 0; // create_queue_virtual's color model for the construction search (experimental)
    int virtual_rounds = 1;
    // Points per virtual queue taken from a quiet root for each of its puyos that touches no puyo of its color:
    // the virtual queues connect such a puyo later more often than unknown pieces do (experimental)
    int isolated_penalty = 0;
    // Under maximize_score, how the virtual queues rank the roots: 0 the summed best scores; 1 their median;
    // 2 the number of queues reaching the fire line (the standard score_fire_chain points), then the sum
    int score_rank = 0;
    // Evaluation points taken per colored puyo touching no puyo of its color, at every searched board (experimental)
    i32 isolated_eval = 0; // With virtual_colors 1: random queues averaged into each of the VIRTUAL_COUNT slots
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
    // Experimental normal-board penalty per unit of imbalance or excess height.
    i32 stack_balance = 0;
    static constexpr int stack_balance_full_cells = 12;
    int stack_balance_end_cells = 40;
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
    // Percent by which a sustained build may fall short of the rate it expects to reach by building
    // on and still fire the large chain it has: waiting is not free while the opponent's clock runs.
    i32 fire_tolerance = 0;
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

// Colored puyos with no orthogonal neighbor of their color
inline i32 isolated_count(const Field& field)
{
    i32 count = 0;
    for (int c = 0; c < 4; ++c) {
        const __m128i bits = field.data[c].data;
        const __m128i near = _mm_srli_si128(bits, 2) | _mm_slli_si128(bits, 2)
            | _mm_srli_epi16(bits, 1) | _mm_slli_epi16(bits, 1);
        FieldBit alone;
        alone.data = _mm_andnot_si128(near, bits);
        count += i32(alone.get_count());
    }
    return count;
}

// The board's evaluation: the shared one plus what only this rule has.
void evaluate_normal(beam::node::Data& node, const beam::eval::Weight& w, const Configs& configs, int* near_chain=nullptr);

inline void evaluate(beam::node::Data& node, const beam::eval::Weight& w, const Configs& configs, int* near_chain=nullptr)
{
    auto shared = w;
    shared.waste_14 = 0;
    if (configs.normal) evaluate_normal(node, shared, configs, near_chain);
    else beam::eval::evaluate(node, shared);
    if (configs.isolated_eval) node.score.eval -= isolated_count(node.field) * configs.isolated_eval;
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
    int held_main = 0; // First-root potential, reusing its ordinary evaluation
    int root_chain = 0;
    bool keeps_main = false; // Configs::score_keep_main_clear: a short root clear that leaves the main
    int isolated = 0; // Configs::isolated_penalty: puyos of the root piece touching no puyo of their color
    i64 throughput = 0;
    bool side_root = false;
    std::vector<i64> projected; // Unpenalized points, one per existing virtual search.
    i64 recovery = 0; // Root-only reconstruction adjustment in score units.
};

inline bool can_keep_building(const Candidate& candidate)
{
    return candidate.root_chain == 0 && candidate.next_room > 0;
}

// A construction root under Configs::maximize_score: non-clearing, or a short clear that keeps the main
inline bool builds_main(const Candidate& candidate)
{
    return can_keep_building(candidate) || (candidate.keeps_main && candidate.next_room > 0);
}

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
    const normal_scoring::Entry* normal = nullptr,
    bool current = false    // the root: the piece about to be placed (normal_space::moves)
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

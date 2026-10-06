#pragma once

#include "layer.h"
#include "eval.h"

namespace beam
{

constexpr size_t BRANCH = 6;
constexpr size_t PRUNE = 5000;

struct Configs
{
    size_t width = 250;
    size_t depth = 16;
    size_t trigger = 130000;
    bool stretch = true;
    // Chain score the search is aiming for: when set, candidates are ranked first by how many sampled
    // queues reach it and only then by their total chain score; 0 keeps the expected-score ranking
    size_t target = 0;
    // Mixes same-color pairs into the sampled queues so the build keeps room for them
    bool zoro = false;
    // Benchmark comparisons can use an exact horizon. Production retains the
    // legacy rounding of sampled tails to an even number of pairs.
    bool exact_depth = false;
};

struct Candidate
{
    move::Placement placement = move::Placement();
    size_t score = 0;
    // Number of sampled queues in which this placement reached Configs::target
    size_t reach = 0;
    // Best chain score after paying for the first move's small clear, summed over queues.
    // The raw score above remains available for fire/target decisions.
    size_t utility = 0;
    i32 clear_puyos = 0;
};

struct Result
{
    std::vector<Candidate> candidates = {};
};

void expand(
    const cell::Pair& pair,
    node::Data& node,
    const eval::Weight& w,
    std::function<void(node::Data&, const move::Placement&, const chain::Score&)> callback
);

void think(
    const cell::Pair& pair,
    std::vector<Candidate>& candidates,
    Layer& parents,
    Layer& children,
    const eval::Weight& w
);

Result search(
    Field field,
    cell::Queue queue,
    eval::Weight w,
    Configs configs = Configs()
);

Result search_multi(
    Field field,
    cell::Queue queue,
    eval::Weight w,
    Configs configs = Configs()
);

cell::Queue get_queue_random(i32 id, size_t count, bool zoro = false, bool exact_count = false);

inline bool operator < (const Candidate& a, const Candidate& b)
{
    return a.score < b.score;
};

// Ranking of candidates whose scores are accumulated over the sampled queues (true when `a` ranks before `b`)
// With a target, the candidates reaching it in more queues come first, then the usual rule breaks ties
inline bool compare(const Candidate& a, const Candidate& b, const Configs& configs)
{
    if (configs.target > 0 && a.reach != b.reach) {
        return a.reach > b.reach;
    }

    if (configs.stretch) {
        if (a.utility != b.utility) {
            return a.utility > b.utility;
        }
        if (a.clear_puyos != b.clear_puyos) {
            return a.clear_puyos < b.clear_puyos;
        }
        return a.score > b.score;
    }

    bool a_enough = a.score / beam::BRANCH >= configs.trigger;
    bool b_enough = b.score / beam::BRANCH >= configs.trigger;

    if (a_enough != b_enough) {
        return a_enough;
    }

    if (a_enough && b_enough) {
        return a.score < b.score;
    }

    if (a.utility != b.utility) {
        return a.utility > b.utility;
    }
    if (a.clear_puyos != b.clear_puyos) {
        return a.clear_puyos < b.clear_puyos;
    }
    return a.score > b.score;
};

};

#include "fire.h"

namespace ai
{

namespace fire
{

std::optional<Decision> decide(
    Field field,
    const cell::Queue& queue,
    const beam::Result& beam,
    i32 trigger
)
{
    if (beam.candidates.empty() || queue.empty()) {
        return {};
    }

    // Biggest chain the pair in hand triggers right away
    auto locks = move::generate(field, queue[0].first == queue[0].second);

    i32 best_now = 0;
    move::Placement best_now_placement = move::Placement();

    for (auto i = 0; i < locks.get_size(); ++i) {
        auto f = field;
        f.drop_pair(locks[i].x, locks[i].r, queue[0]);
        auto pop = f.pop();

        if (f.is_dead(rule::TSU)) {
            continue;
        }

        auto chain = chain::get_score(pop);

        if (chain.score > best_now) {
            best_now = chain.score;
            best_now_placement = locks[i];
        }
    }

    bool enough = best_now >= trigger;
    bool panic = field.get_count() >= PANIC_COUNT && best_now >= PANIC_SCORE;

    if (!enough && !panic) {
        return {};
    }

    return Decision {
        .placement = best_now_placement,
        .eval = best_now
    };
};

};

};

#include "fire.h"

namespace ai
{

namespace fire
{

// Biggest chain the pair triggers right away on the field, with the placement that triggers it
static std::pair<i32, move::Placement> get_best_now(Field& field, const cell::Pair& pair)
{
    auto locks = move::generate(field, pair.first == pair.second);

    i32 best = 0;
    move::Placement best_placement = move::Placement();

    for (auto i = 0; i < locks.get_size(); ++i) {
        auto f = field;
        f.drop_pair(locks[i].x, locks[i].r, pair);
        auto pop = f.pop();

        if (f.get_height(2) > 11) {
            continue;
        }

        auto chain = chain::get_score(pop);

        if (chain.score > best) {
            best = chain.score;
            best_placement = locks[i];
        }
    }

    return { best, best_placement };
};

// Biggest chain the next pair can trigger after the placement, or -1 when the placement kills
static i32 get_best_next(Field field, const move::Placement& placement, const cell::Pair& pair, const cell::Pair& next)
{
    field.drop_pair(placement.x, placement.r, pair);
    auto pop = field.pop();

    if (field.get_height(2) > 11) {
        return -1;
    }

    // The placement fires a chain itself
    auto chain = chain::get_score(pop);

    if (chain.score >= beam::PRUNE) {
        return chain.score;
    }

    return get_best_now(field, next).first;
};

std::optional<Decision> decide(
    Field field,
    const cell::Queue& queue,
    const beam::Result& beam,
    i32 trigger,
    const Policy& policy
)
{
    if (beam.candidates.empty() || queue.empty()) {
        return {};
    }

    // Biggest chain the pair in hand triggers right away
    auto [best_now, best_now_placement] = get_best_now(field, queue[0]);

    i32 count = field.get_count();

    bool enough = best_now >= trigger;
    bool panic = count >= policy.panic_count && best_now >= PANIC_SCORE;

    if (enough || panic) {
        return Decision {
            .placement = best_now_placement,
            .eval = best_now
        };
    }

    if (queue.size() < 2) {
        return {};
    }

    // Unburying: the field is about to overflow and nothing worth firing is in hand, so the chain's
    // trigger got covered; the beam keeps betting on a color, this picks the placement that leaves the
    // biggest chain fireable with the next pair instead
    if (count >= policy.panic_count) {
        std::optional<Decision> best = {};

        for (auto& c : beam.candidates) {
            i32 next = get_best_next(field, c.placement, queue[0], queue[1]);

            if (next < 0) {
                continue;
            }

            if (!best.has_value() || next > best->eval) {
                best = Decision { .placement = c.placement, .eval = next };
            }
        }

        if (best.has_value() && best->eval >= PANIC_SCORE) {
            return best;
        }

        return {};
    }

    // Guard: late in the build, a chain worth keeping must stay fireable with the next pair
    // The beam scores a placement by the best chain of a few sampled queues, which always bring every
    // color within 2 pairs, so near the end it covers the trigger expecting a color the real queue may
    // not bring, and the whole chain is lost
    // The guard steps in only when the beam's choice would lose most of the chain (a rebuild of the
    // head keeps most of it and is left alone, as the rules tried before showed); then, among the
    // beam's candidates in its order, the first one that keeps (or grows) the chain in hand is played,
    // and when none does the chain is fired before it is lost
    if (!policy.guard || count < policy.guard_count || best_now < policy.guard_score) {
        return {};
    }

    i32 first = get_best_next(field, beam.candidates.front().placement, queue[0], queue[1]);

    if (first >= 0 && i64(first) * 100 >= i64(best_now) * policy.guard_keep) {
        return {};
    }

    for (auto& c : beam.candidates) {
        i32 next = get_best_next(field, c.placement, queue[0], queue[1]);

        if (next >= best_now) {
            return Decision {
                .placement = c.placement,
                .eval = i32(c.score / beam::BRANCH)
            };
        }
    }

    if (!policy.guard_fire) {
        return {};
    }

    return Decision {
        .placement = best_now_placement,
        .eval = best_now
    };
};

};

};

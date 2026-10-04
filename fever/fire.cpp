#include "fire.h"

namespace fever
{

namespace fire
{

std::optional<Decision> best_now(
    Field field,
    const piece::Piece& piece,
    const rule::Rule& rules
)
{
    std::optional<Decision> result = {};

    auto locks = move::generate(field, piece, rules);

    for (auto i = 0; i < locks.get_size(); ++i) {
        auto f = field;

        if (!f.drop_piece(locks[i].x, locks[i].r, piece, rules)) {
            continue;
        }

        auto pop = f.pop();

        if (f.is_dead(rules)) {
            continue;
        }

        auto chain = chain::get_score(pop);

        if (!result ||
            chain.count > result->chain.count ||
            (chain.count == result->chain.count && chain.score > result->chain.score)) {
            result = Decision { .placement = locks[i], .chain = chain };
        }
    }

    return result;
};

std::optional<Decision> decide(
    Field field,
    const piece::Piece& piece,
    const Result& search,
    i32 trigger,
    const rule::Rule& rules
)
{
    if (search.candidates.empty()) {
        return {};
    }

    auto now = best_now(field, piece, rules);

    if (!now) {
        return {};
    }

    bool enough = now->chain.count >= trigger;
    bool panic = i32(field.get_count()) >= PANIC_COUNT && now->chain.count >= PANIC_CHAIN;

    if (!enough && !panic) {
        return {};
    }

    return now;
};

};

std::optional<Choice> think(
    Field field,
    const Queue& queue,
    const dropset::Character& character,
    u64 index,
    const beam::eval::Weight& w,
    Configs configs
)
{
    if (queue.empty()) {
        return {};
    }

    auto search = search_multi(field, queue, character, index, w, configs);

    // No placement survives
    if (search.candidates.empty()) {
        return {};
    }

    // The fire policy may take over
    auto decision = fire::decide(field, queue[0], search, configs.trigger, configs.rules);

    if (decision) {
        return Choice {
            .placement = decision->placement,
            .chain = decision->chain.count,
            .score = size_t(decision->chain.score),
            .fire = true
        };
    }

    auto& best = search.candidates.front();

    return Choice {
        .placement = best.placement,
        .chain = best.chain,
        .score = best.score / VIRTUAL_COUNT,
        .fire = false
    };
};

};

#include "fire.h"

namespace fever
{

namespace fire
{

static bool is_better(const Decision& a, const Decision& b)
{
    if (a.chain.count != b.chain.count) {
        return a.chain.count > b.chain.count;
    }

    if (a.moves != b.moves) {
        return a.moves < b.moves;
    }

    return a.chain.score > b.chain.score;
};

// Tries every placement of queue[depth..], keeping the best chain popped by any single placement
static void walk(
    Field& field,
    const Queue& queue,
    size_t depth,
    const move::Placement* first,
    const rule::Rule& rules,
    std::optional<Decision>& best
)
{
    auto locks = move::generate(field, queue[depth], rules);

    for (auto i = 0; i < locks.get_size(); ++i) {
        auto f = field;

        if (!f.drop_piece(locks[i].x, locks[i].r, queue[depth], rules)) {
            continue;
        }

        auto pop = f.pop();

        if (f.is_dead(rules)) {
            continue;
        }

        if (rules.margin) {
            u8 heights[6];
            f.get_heights(heights);
            if (rule::is_unsafe(heights, rules)) {
                continue;
            }
        }

        auto decision = Decision {
            .placement = depth == 0 ? locks[i] : *first,
            .chain = chain::get_score(pop),
            .moves = i32(depth) + 1
        };

        if (!best || is_better(decision, *best)) {
            best = decision;
        }

        if (depth + 1 < queue.size()) {
            walk(f, queue, depth + 1, &decision.placement, rules, best);
        }
    }
};

std::optional<Decision> best_visible(
    Field field,
    const Queue& queue,
    const rule::Rule& rules
)
{
    std::optional<Decision> result = {};

    if (!queue.empty()) {
        walk(field, queue, 0, nullptr, rules, result);
    }

    return result;
};

std::optional<Decision> best_now(
    Field field,
    const piece::Piece& piece,
    const rule::Rule& rules
)
{
    return best_visible(field, Queue { piece }, rules);
};

i32 get_required(i32 count, const Configs& configs)
{
    i32 required = configs.trigger;

    if (configs.panic_step <= 0) {
        required = count >= configs.panic_count ? std::min(configs.panic_chain, configs.trigger) : configs.trigger;
    }
    else {
        // Links added below panic_count round up, links removed above it round down
        i32 delta = configs.panic_count - count;
        i32 links = delta >= 0 ? (delta + configs.panic_step - 1) / configs.panic_step : -((-delta) / configs.panic_step);

        required = std::clamp(configs.panic_chain + links, 1, std::max(1, configs.trigger));
    }

    // A game that has gone on without the chain coming together settles for less, move by move
    if (configs.patience > 0 && configs.moves >= configs.patience) {
        i32 less = (configs.moves - configs.patience) / std::max(1, configs.patience_step);

        required = std::min(required, std::max(2, configs.trigger - less));
    }

    return required;
};


std::optional<Decision> decide(
    Field field,
    const Queue& queue,
    const Result& search,
    const Configs& configs
)
{
    if (search.candidates.empty()) {
        return {};
    }

    // Every sequence of placements is tried, which is only affordable for the pieces a player sees.
    // A client that reads further ahead still gets its fire decision from the first VISIBLE pieces.
    auto best = best_visible(field, Queue(queue.begin(), queue.begin() + std::min(queue.size(), VISIBLE)), configs.rules);

    if (!best) {
        return {};
    }

    bool enough = best->chain.count >= get_required(i32(field.get_count()), configs);
    bool shave = false;

    if (configs.shave_chain > 0 && best->chain.count >= configs.shave_chain) {
        auto f = field;
        auto& placement = search.candidates.front().placement;

        if (f.drop_piece(placement.x, placement.r, queue[0], configs.rules)) {
            auto count = f.pop_count();

            shave = count > 0 && count < configs.shave_chain;
        }
    }

    if (!enough && !shave) {
        return {};
    }

    return best;
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
    auto decision = fire::decide(field, queue, search, configs);

    if (decision) {
        return Choice {
            .placement = decision->placement,
            .chain = decision->chain.count,
            .score = size_t(decision->chain.score),
            .fire = true,
            .fire_moves = decision->moves
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

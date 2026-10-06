#include "search.h"

namespace fever
{

// Expands node
void expand(
    const piece::Piece& piece,
    beam::node::Data& node,
    const beam::eval::Weight& w,
    const rule::Rule& rules,
    std::function<void(beam::node::Data&, const move::Placement&, const chain::Score&)> callback
)
{
    // Generates moves
    auto locks = move::generate(node.field, piece, rules);

    for (auto i = 0; i < locks.get_size(); ++i) {
        // Creates child node
        auto child = node;

        // Drops piece
        auto drop = child.field.drop_piece(locks[i].x, locks[i].r, piece, rules);

        if (!drop) {
            continue;
        }

        // Pops child field
        auto pop = child.field.pop();

        // Checks for death
        if (child.field.is_dead(rules)) {
            continue;
        }

        if (rules.margin) {
            u8 heights[6];
            child.field.get_heights(heights);
            if (rule::is_unsafe(heights, rules)) {
                continue;
            }
        }

        // Evaluates action
        i32 tear = drop->split;
        i32 waste = pop.get_size();

        beam::eval::action(child, tear, waste, w);

        // Callback
        callback(child, locks[i], chain::get_score(pop));
    }
};

// Does 1 iteration of beam search from the parents layer to the children layer
static void think(
    const piece::Piece& piece,
    std::vector<Candidate>& candidates,
    beam::Layer& parents,
    beam::Layer& children,
    const beam::eval::Weight& w,
    const rule::Rule& rules,
    const Configs& configs,
    size_t depth
)
{
    // Sorts the parents layer
    parents.sort();

    std::vector<i64> reached(configs.aim ? candidates.size() : 0, INT64_MIN);

    // Expands each parent to the next layer
    for (auto& node : parents.data) {
        fever::expand(piece, node, w, rules, [&] (beam::node::Data& child, const move::Placement& placement, const chain::Score& chain) {
            // Updates max chain found
            auto& candidate = candidates[child.index];

            candidate.score = std::max(candidate.score, size_t(chain.score));
            candidate.chain = std::max(candidate.chain, chain.count);

            // Prunes children that triggered big chains
            if (chain.count >= fever::PRUNE_CHAIN) {
                return;
            }

            // Every node of a layer is at the same move of the cycle, so the field alone identifies it
            auto hash = beam::node::get_hash(child);

            // Probes the transposition table
            auto [found, entry] = children.table.get(hash);

            if (found) {
                // Transposition table cut
                if (child.score.action < entry->action) {
                    return;
                }

                child.score.eval = entry->eval;
            }
            else {
                fever::evaluate(child, w, configs);
            }

            // Stores the entry in the transposition table
            children.table.set(entry, hash, child.score.action, child.score.eval);

            if (configs.aim) {
                reached[child.index] = std::max(reached[child.index], i64(child.score.eval) + child.score.action);
            }

            // Adds children to the next layer
            children.add(child);
        });
    }

    // Clears the parents layer
    parents.clear();

    for (size_t i = 0; i < reached.size(); ++i) {
        if (reached[i] != INT64_MIN) {
            candidates[i].aim = reached[i];
        }
        else if (candidates[i].aim > AIM_LOST / 2) {
            candidates[i].aim = AIM_LOST + i64(depth) * 1000000;
        }
    }
};

// Beam search
Result search(
    Field field,
    const Queue& queue,
    const beam::eval::Weight& w,
    Configs configs
)
{
    auto result = Result();

    if (queue.empty()) {
        return result;
    }

    // Creates root
    auto root = beam::node::Data {
        .field = field,
        .score = { 0, 0 },
        .index = -1
    };

    // Creates stack
    std::array<beam::Layer, 2> layers = {
        beam::Layer(configs.width),
        beam::Layer(configs.width)
    };

    // Initializes candidates
    fever::expand(
        queue[0],
        root,
        w,
        configs.rules,
        [&] (beam::node::Data& child, const move::Placement& placement, const chain::Score& chain) {
            // Creates candidate
            auto candidate = Candidate();

            candidate.placement = placement;
            candidate.score = chain.score;
            candidate.chain = chain.count;

            // Updates child
            child.index = i32(result.candidates.size());
            fever::evaluate(child, w, configs);
            candidate.aim = i64(child.score.eval) + child.score.action;

            // Pushes
            result.candidates.push_back(candidate);
            layers[0].data.push_back(child);
        }
    );

    // If there aren't any candidates, stops searching
    if (result.candidates.empty()) {
        return result;
    }

    // Searches
    for (size_t i = 0; i + 1 < queue.size(); ++i) {
        fever::think(
            queue[i + 1],
            result.candidates,
            layers[i & 1],
            layers[(i + 1) & 1],
            w,
            configs.rules,
            configs,
            i + 1
        );

        bool enough = false;

        for (auto& c : result.candidates) {
            if (c.chain >= configs.trigger) {
                enough = true;
                break;
            }
        }

        if (enough) {
            break;
        }
    }

    return result;
};

// Beam search with multiple threads and virtual queues, see beam::search_multi
Result search_multi(
    Field field,
    const Queue& queue,
    const dropset::Character& character,
    u64 index,
    const beam::eval::Weight& w,
    Configs configs
)
{
    auto result = Result();

    // Creates future queues
    std::vector<Queue> queues;

    for (i32 i = 0; i < VIRTUAL_COUNT; ++i) {
        auto q = queue;

        if (configs.depth > queue.size()) {
            auto future = create_queue_virtual(character, i, configs.depth - queue.size(), index + queue.size());

            // Unknown cycle: no shape is guessed
            if (!future) {
                return result;
            }

            q.insert(q.end(), future->begin(), future->end());
        }

        queues.push_back(q);
    }

    // Searching multiple queues at the same time
    std::vector<Result> results(queues.size());
    std::vector<std::thread> threads;

    for (size_t i = 0; i < queues.size(); ++i) {
        threads.emplace_back([&] (size_t id) {
            results[id] = fever::search(field, queues[id], w, configs);
        }, i);
    }

    for (auto& t : threads) {
        t.join();
    }

    // Accumulates the biggest chains of each candidate
    // The first move is the same on every queue, so the candidates line up
    for (auto& b : results) {
        if (b.candidates.empty()) {
            continue;
        }

        if (result.candidates.empty()) {
            result = b;
            continue;
        }

        for (auto& c1 : result.candidates) {
            for (auto& c2 : b.candidates) {
                if (c1.placement == c2.placement) {
                    c1.score += c2.score;
                    c1.aim += c2.aim;
                    c1.chain = std::max(c1.chain, c2.chain);
                    break;
                }
            }
        }
    }

    // Sorts candidates by their total accumulated scores
    std::stable_sort(
        result.candidates.begin(),
        result.candidates.end(),
        [&] (const Candidate& a, const Candidate& b) {
            if (configs.aim) {
                return a.aim > b.aim;
            }

            if (configs.stretch) {
                return a.score > b.score;
            }

            bool a_enough = a.chain >= configs.trigger;
            bool b_enough = b.chain >= configs.trigger;

            if (a_enough && b_enough) {
                return a.score < b.score;
            }

            return a.score > b.score;
        }
    );

    return result;
};

};

#include "../fever_battle/physics.h"
#include "fire.h"
#include "rebuild.h"
#include "normal_space.h"

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
    const normal_scoring::Entry* normal,
    std::optional<Decision>& best,
    const Configs* sustained = nullptr, int elapsed = 0
)
{
    auto locks = normal_space::moves(field, queue[depth], rules);

    for (auto i = 0; i < locks.get_size(); ++i) {
        auto f = field;
        int frames=elapsed;
        if (sustained) {
            const auto distances=fever_battle::split_distances(field,queue[depth],locks[i].x,locks[i].r);
            const int split=*std::max_element(distances.begin(),distances.end());
            frames+=std::max(sustained->pace_frames,55+split*2);
        }

        if (!f.drop_piece(locks[i].x, locks[i].r, queue[depth], rules)) {
            continue;
        }

        auto locked=f;
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

        if (sustained && pop.get_size()) {
            const auto features=fever_battle::fall_features(locked,pop);
            frames+=24;
            for (int j=0;j<pop.get_size();++j) frames+=fever_battle::link_frames(features[j],j==pop.get_size()-1);
        }
        auto decision = Decision {
            .placement = depth == 0 ? locks[i] : *first,
            .chain = normal ? normal_scoring::score(pop, *normal) : chain::get_score(pop),
            .frames = frames,
            .moves = i32(depth) + 1
        };

        const auto rate=[&](const Decision& d) {
            return i64(d.chain.score)*60000/std::max(1,d.frames+sustained->elapsed_build_frames);
        };
        const bool eligible=!sustained || decision.chain.count>=sustained->sustained_min_chain;
        if (eligible && (!best || (sustained ? rate(decision)>rate(*best) : is_better(decision, *best)))) {
            best = decision;
        }

        if (depth + 1 < queue.size()) {
            walk(f, queue, depth + 1, &decision.placement, rules, normal, best, sustained, frames);
        }
    }
};

std::optional<Decision> best_visible(
    Field field,
    const Queue& queue,
    const rule::Rule& rules,
    const normal_scoring::Entry* normal, const Configs* sustained
)
{
    std::optional<Decision> result = {};

    if (!queue.empty()) {
        walk(field, queue, 0, nullptr, rules, normal, result, sustained);
    }

    return result;
};

std::optional<Decision> best_now(
    Field field,
    const piece::Piece& piece,
    const rule::Rule& rules,
    const normal_scoring::Entry* normal
)
{
    return best_visible(field, Queue { piece }, rules, normal);
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
    auto best = best_visible(field, Queue(queue.begin(), queue.begin() + std::min(queue.size(), VISIBLE)), configs.rules, configs.normal);

    if (!best) {
        return {};
    }

    if (configs.sustained && get_required(i32(field.get_count()),configs)>1) {
        auto large=best_visible(field,Queue(queue.begin(),queue.begin()+std::min(queue.size(),VISIBLE)),
            configs.rules,configs.normal,&configs);
        if (!large) return {};
        const i64 actual=i64(large->chain.score)*60000/std::max(1,large->frames+configs.elapsed_build_frames);
        const i64 future=search.candidates.front().throughput/VIRTUAL_COUNT;
        // Actual large chains compete with construction; no perfect-form requirement.
        if (actual>=future || large->chain.count>=configs.build_chain) return large;
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

    if (configs.construction_scoring) configs.normal = normal_scoring::find(character.id);
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
            .fire_moves = decision->moves,
            .search_depths = search.virtual_depths
        };
    }

    json reconstruction = nullptr;
    if (configs.rebuild && !configs.aim && configs.stretch)
        reconstruction = rebuild::rank(field, queue, search, w, configs);
    std::stable_sort(search.candidates.begin(),search.candidates.end(),
        [&](const Candidate& a,const Candidate& b){
            if ((a.next_room>0)!=(b.next_room>0)) return a.next_room>0;
            return configs.sustained && a.throughput>b.throughput;
        });
    auto chosen = search.candidates.begin();
    if (configs.preserve_build) {
        const auto quiet = std::find_if(search.candidates.begin(), search.candidates.end(), [&](const Candidate& candidate) {
            auto next = field;
            const auto& move = candidate.placement;
            return candidate.next_room>0 && next.drop_piece(move.x, move.r, queue[0], configs.rules) && next.pop().get_size() <= 2;
        });
        if (quiet != search.candidates.end()) chosen = quiet;
    }
    auto& best = *chosen;

    return Choice {
        .placement = best.placement,
        .chain = best.chain,
        .score = best.score / VIRTUAL_COUNT,
        .fire = false,
        .search_depths = search.virtual_depths,
        .reconstruction = reconstruction
    };
};

};

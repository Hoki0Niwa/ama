#include "../fever_battle/physics.h"
#include "fire.h"
#include "rebuild.h"
#include "normal_space.h"
#include "evaluation.h"
#include <tuple>

namespace fever
{

namespace fire
{

// The standard chain whose points the repair and rebuild comparisons count queues to (Configs::score_fire_chain
// raises only the firing threshold)
constexpr int REPAIR_REFERENCE_CHAIN = 14;

static bool is_better(const Decision& a, const Decision& b, bool maximize_score)
{
    if (maximize_score) {
        if (a.chain.score != b.chain.score) return a.chain.score > b.chain.score;
        return a.moves < b.moves;
    }

    if (a.chain.count != b.chain.count) {
        return a.chain.count > b.chain.count;
    }

    if (a.moves != b.moves) {
        return a.moves < b.moves;
    }

    return a.chain.score > b.chain.score;
};

struct ScoreLookahead {
    struct Continuation {
        int potential_points = 0;
        int retained_points = 0;
        int visible_points = 0;
        bool quiet_root = false;
        bool quiet_visible = false;
        bool repair_root = false;
        bool cleanup_root = false;
        bool removes_garbage = false;
        bool survives_visible = false;
    };

    const beam::eval::Weight& weights;
    const Configs& configs;
    size_t forecast_depth;
    std::array<Continuation, 24> roots{};
    std::optional<Decision> opening_main;
    std::optional<Decision> opening_fallback;
    std::optional<Decision> opening_capacity_fire;

    Continuation& at(move::Placement placement) {
        return roots[4 * placement.x + int(placement.r)];
    }
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
    const Configs* sustained = nullptr, int elapsed = 0,
    Small* small = nullptr, std::array<move::Placement, 3>* path = nullptr, bool clean = true,
    bool maximize_score = false, ScoreLookahead* lookahead = nullptr, u32 root_placements = 0xffffffu,
    bool no_discard = true
)
{
    auto locks = normal_space::moves(field, queue[depth], rules, depth == 0);   // the root: the piece about to be placed
    const int opening_minimum = lookahead ? lookahead->configs.score_opening_min_chain : 0;
    bool quiet_lock = false;
    std::optional<Decision> fallback;

    for (auto i = 0; i < locks.get_size(); ++i) {
        if (!depth && !(root_placements & (1u << (4 * locks[i].x + int(locks[i].r))))) continue;
        auto f = field;
        int frames=elapsed;
        if (sustained) {
            const auto distances=fever_battle::split_distances(field,queue[depth],locks[i].x,locks[i].r);
            const int split=*std::max_element(distances.begin(),distances.end());
            frames+=std::max(sustained->pace_frames,55+split*2);
        }

        const auto dropped = f.drop_piece(locks[i].x, locks[i].r, queue[depth], rules);
        if (!dropped) {
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

        if (lookahead) {
            auto& root = lookahead->at(decision.placement);
            if (depth == 0) {
                root.repair_root = !dropped->discarded && pop.get_size() > 0 && pop.get_size() <= 3
                    && f.get_count() < field.get_count();
                const auto garbage = int(cell::Type::GARBAGE);
                const int left = f.data[garbage].get_count();
                root.removes_garbage = left < field.data[garbage].get_count();
                root.cleanup_root = lookahead->configs.score_repair_damaged && !dropped->discarded
                    && pop.get_size() > 0 && pop.get_size() <= 5 && int(f.get_count()) - left >= 24
                    && (int(field.get_count()) - int(f.get_count()) >= 8
                        || root.removes_garbage);
            }
            if (depth + 1 == queue.size() && no_discard && !dropped->discarded)
                root.survives_visible = true;
            if (decision.chain.count >= opening_minimum) {
                root.visible_points = std::max(root.visible_points, decision.chain.score);
                if (opening_minimum && (!lookahead->opening_main || is_better(decision, *lookahead->opening_main, true))) {
                    lookahead->opening_main = decision;
                }
            }
            if (decision.chain.count >= lookahead->configs.score_reserve_chain && decision.chain.count < opening_minimum &&
                    (!fallback || is_better(decision, *fallback, true))) fallback = decision;
            quiet_lock |= !pop.get_size() && !dropped->discarded;
            if (clean && !dropped->discarded) {
                if (depth == 0) root.quiet_root = pop.get_size() == 0;
                if (depth + 1 == queue.size() && pop.get_size() == 0) root.quiet_visible = true;
                if (depth > 0) root.retained_points = std::max(root.retained_points, decision.chain.score);
                if (depth < lookahead->forecast_depth && pop.get_size() == 0) {
                    const auto estimate = potential(f, lookahead->weights, lookahead->configs);
                    root.potential_points = std::max(root.potential_points, estimate.score);
                }
            }
        }

        if (small && depth < 3) {
            (*path)[depth] = locks[i];
            if (clean && !dropped->discarded && decision.chain.count >= 2 && decision.chain.count <= 4
                    && normal_space::room(f, 1)) {
                const int material = f.get_count() - f.data[int(cell::Type::GARBAGE)].get_count();
                if (material >= 24) {
                    u8 h[6]; f.get_heights(h);
                    const auto [two, three] = beam::eval::get_link_23(f);
                    const i64 rank = material*100 + two*20 + three*40
                        - get_hill(h)*50 - int(depth)*400 + decision.chain.score/10;
                    if (depth == 0) small->immediate.push_back({
                        {"choice",{{"x",locks[i].x},{"r",std::string(1,"URDL"[int(locks[i].r)])}}},
                        {"conversion_chain",decision.chain.count},{"conversion_points",decision.chain.score},
                        {"remaining_material",material},{"rank",rank}});
                    if (rank > small->rank) {
                        small->found = true; small->rank = rank; small->decision = decision;
                        small->after = f; small->path = *path; small->material = material;
                    }
                }
            }
        }

        const auto rate=[&](const Decision& d) {
            return i64(d.chain.score)*60000/std::max(1,d.frames+sustained->elapsed_build_frames);
        };
        const bool eligible=!sustained || decision.chain.count>=sustained->sustained_min_chain;
        if (eligible && (!best || (sustained ? rate(decision)>rate(*best) : is_better(decision, *best, maximize_score)))) {
            best = decision;
        }

        if (depth + 1 < queue.size()) {
            walk(f, queue, depth + 1, &decision.placement, rules, normal, best, sustained, frames, small, path,
                clean && pop.get_size()==0 && !dropped->discarded, maximize_score, lookahead,
                root_placements, no_discard && !dropped->discarded);
        }
    }
    if (fallback) {
        auto& best_fallback = lookahead->opening_fallback;
        auto& capacity = lookahead->opening_capacity_fire;
        if (!best_fallback || is_better(*fallback, *best_fallback, true)) best_fallback = fallback;
        if (!quiet_lock && (!capacity || is_better(*fallback, *capacity, true))) capacity = fallback;
    }
};

std::optional<Decision> best_visible(
    Field field,
    const Queue& queue,
    const rule::Rule& rules,
    const normal_scoring::Entry* normal, const Configs* sustained, Small* small, bool maximize_score, u32 root_placements
)
{
    std::optional<Decision> result = {};

    if (!queue.empty()) {
        std::array<move::Placement, 3> path{};
        walk(field, queue, 0, nullptr, rules, normal, result, sustained, 0, small, &path, true, maximize_score, nullptr, root_placements);
    }

    return result;
};

std::optional<Decision> best_now(
    Field field,
    const piece::Piece& piece,
    const rule::Rule& rules,
    const normal_scoring::Entry* normal,
    bool maximize_score
)
{
    return best_visible(field, Queue { piece }, rules, normal, nullptr, nullptr, maximize_score);
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
    const Queue visible(queue.begin(), queue.begin() + std::min(queue.size(), VISIBLE));
    auto best = best_visible(field, visible, configs.rules, configs.normal, nullptr, nullptr, false, configs.root_placements);

    if (!best) {
        return {};
    }

    if (configs.sustained && get_required(i32(field.get_count()),configs)>1) {
        auto large=best_visible(field,visible,
            configs.rules,configs.normal,&configs,nullptr,false,configs.root_placements);
        if (!large) return {};
        const i64 actual=i64(large->chain.score)*60000/std::max(1,large->frames+configs.elapsed_build_frames);
        const i64 future=search.candidates.front().throughput/VIRTUAL_COUNT;
        // Actual large chains compete with construction; no perfect-form requirement.
        const i64 tolerance=std::clamp(configs.fire_tolerance,0,90);
        if (actual*100>=future*(100-tolerance) || large->chain.count>=configs.build_chain) return large;
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

struct ScorePlan {
    std::optional<Decision> fire;
    const Candidate* build;
    int fire_line;
    int repair_line; // Target of the repair and rebuild comparisons, independent of the fire line
    int potential_points = 0;
    json rebuild = nullptr;
    bool visible_fire_protected = false;
    bool repair = false;
};

static int target_bags(const Candidate& candidate, int target)
{
    return int(std::count_if(candidate.projected.begin(), candidate.projected.end(),
        [target](i64 points) { return points >= target; }));
}

static void consider_damaged_repair(const Result& search, ScoreLookahead& lookahead, int held,
                                    const Decision& available, ScorePlan& plan)
{
    const auto& configs = lookahead.configs;
    if (!configs.score_repair_damaged || held >= 8 || available.chain.count >= configs.score_reserve_chain
            || !plan.rebuild.is_null()) return;
    const auto baseline = plan.fire ? std::find_if(search.candidates.begin(), search.candidates.end(),
        [&](const Candidate& c) { return c.placement == plan.fire->placement; }) : search.candidates.end();
    const Candidate* current = plan.fire && baseline != search.candidates.end() ? &*baseline : plan.build;
    if (current->projected.size() != VIRTUAL_COUNT) return;
    const int reserve = normal_scoring::pure(REPAIR_REFERENCE_CHAIN - 1, *configs.normal);
    const auto quality = [&](const Candidate& c) {
        return std::tuple{target_bags(c, plan.repair_line), target_bags(c, reserve), c.score};
    };
    const auto base = quality(*current);
    const Candidate* best = current;
    for (const auto& candidate : search.candidates) {
        const auto& route = lookahead.at(candidate.placement);
        if (!route.cleanup_root || !route.survives_visible || candidate.projected.size() != VIRTUAL_COUNT
                || candidate.score <= current->score || candidate.held_main < held - 1) continue;
        const auto rank = quality(candidate);
        const int full = std::get<0>(rank);
        const bool restores_main = candidate.held_main >= 8 && full >= VIRTUAL_COUNT / 2;
        const bool opens_rebuild = route.removes_garbage && full > VIRTUAL_COUNT / 2;
        if ((!restores_main && !opens_rebuild) || full <= std::get<0>(base) || rank <= quality(*best)) continue;
        int improving = 0;
        for (size_t i = 0; i < VIRTUAL_COUNT; ++i)
            improving += candidate.projected[i] > current->projected[i];
        if (improving > VIRTUAL_COUNT / 2) best = &candidate;
    }
    if (best == current) return;
    plan.fire.reset();
    plan.build = best;
    plan.repair = true;
}

// Reuse the beam's per-root forecasts: a root that clears below the line
// only reaches it in a bag if it finds a new main after that clear.
static void consider_score_rebuild(Field field, const Queue& queue, const Queue& visible, const Result& search,
                                   const dropset::Character& character, u64 index, const beam::eval::Weight& w,
                                   const Configs& configs, ScoreLookahead& lookahead,
                                   int available_points, ScorePlan& plan)
{
    const int before = int(field.get_count());
    if (!configs.score_rebuild || configs.moves < 12 || before < 56 || visible.size() < 2 ||
            available_points >= plan.repair_line || plan.potential_points >= plan.repair_line) return;

    int quiet = 0, baseline_bags = 0;
    size_t baseline_points = 0;
    for (const auto& candidate : search.candidates) {
        if (!can_keep_building(candidate) || !lookahead.at(candidate.placement).quiet_root) continue;
        ++quiet;
        baseline_bags = std::max(baseline_bags, target_bags(candidate, plan.repair_line));
        baseline_points = std::max(baseline_points, candidate.score);
    }
    int coming_cells = 0;
    for (const auto& piece : visible) coming_cells += int(piece::cell_count(piece.shape));
    const int capacity = 4 * 13 + 2 * (11 - configs.rules.margin);
    if ((quiet > 4 && before + coming_cells < capacity) || baseline_bags > 2) return;
    const int required_bags = quiet > 0 ? 4 : 3;

    struct Clear {
        Field after;
        Decision decision;
        int remaining, colors, shape;
        bool standard;
    };
    std::vector<Clear> probes;
    std::tuple<bool, int, int, size_t> best{};
    const auto accept = [&](const Clear& clear, const Candidate& forecast, const char* source) {
        // Buying room may cost a little average score. Keep the board's
        // material when more of the same bags reach the main's score line.
        if (forecast.projected.size() != VIRTUAL_COUNT) return;
        const int bags = target_bags(forecast, plan.repair_line);
        if (bags < required_bags || bags <= baseline_bags || forecast.score * 100 < baseline_points * 98) return;
        // A light clear leaves less room to repair. A few good futures are
        // insufficient if the average does not even reach the fire line.
        if (!clear.standard && forecast.score < size_t(plan.repair_line) * VIRTUAL_COUNT) return;

        const auto rank = std::tuple{clear.standard, clear.colors, bags, forecast.score};
        if (rank <= best) return;
        best = rank;
        plan.fire = clear.decision;
        plan.rebuild = {{"before_cells", before}, {"after_cells", clear.remaining},
            {"remaining_colors", clear.colors}, {"target_points", plan.repair_line},
            {"baseline_target_bags", baseline_bags}, {"rebuild_target_bags", bags},
            {"baseline_average", baseline_points / VIRTUAL_COUNT},
            {"rebuild_average", forecast.score / VIRTUAL_COUNT}, {"forecast_source", source}};
        if (!clear.standard) plan.rebuild["relief"] = "light";
    };
    for (const auto& candidate : search.candidates) {
        if (!candidate.root_chain) continue;
        auto after = field;
        const auto& move = candidate.placement;
        const auto placed = after.drop_piece(move.x, move.r, visible[0], configs.rules);
        if (!placed || placed->discarded) continue;
        auto masks = after.pop();
        const auto chain = normal_scoring::score(masks, *configs.normal);
        const int remaining = int(after.get_count());
        const int colors = remaining - int(after.data[int(cell::Type::GARBAGE)].get_count());
        const bool standard = remaining <= 52 && before - remaining >= 8;
        if (chain.score >= plan.repair_line || remaining > 58 || before - remaining < 3 ||
                colors < 28 || !normal_space::room(after, configs.rules.margin)) continue;

        auto moves = normal_space::moves(after, visible[1], configs.rules);
        if (!normal_space::has_open_move(after, visible[1], moves, configs.rules)) continue;

        Clear clear{after, Decision{.placement = move, .chain = chain, .moves = 1}, remaining, colors,
            potential(after, w, configs).value, standard};
        accept(clear, candidate, "shared_beam");
        if (std::none_of(probes.begin(), probes.end(), [&](const Clear& p) { return after == p.after; })) {
            probes.push_back(clear);
        }
    }
    if (probes.empty()) return;

    // The shared beam can prune a promising cleared board before it rebuilds.
    // Probe at most two boards that could preserve more material, on the same horizon.
    std::stable_sort(probes.begin(), probes.end(), [](const Clear& a, const Clear& b) {
        return std::tuple{a.standard, a.colors, a.shape} > std::tuple{b.standard, b.colors, b.shape};
    });
    const Queue suffix(queue.begin() + 1, queue.end());
    auto repair = configs;
    repair.width = std::min<size_t>(64, configs.width);
    repair.depth = std::max(suffix.size(), configs.depth - 1);
    repair.side_frontier_slots = 0;
    for (size_t i = 0; i < std::min<size_t>(2, probes.size()); ++i) {
        const auto& clear = probes[i];
        if (std::tuple{clear.standard, clear.colors} <= std::tuple{std::get<0>(best), std::get<1>(best)}) break;
        const auto recovery = search_multi(clear.after, suffix, character, index + 1, w, repair);
        for (const auto& forecast : recovery.candidates) {
            if (can_keep_building(forecast)) accept(clear, forecast, "recovery_probe");
        }
    }
}

static ScorePlan score_plan(Field field, const Queue& queue, const Result& search,
                           const dropset::Character& character, u64 index,
                           const beam::eval::Weight& w, const Configs& configs)
{
    // Like the Tsu DFS policy, first play the known pieces, then estimate
    // how much the shape can pop with hypothetical trigger puyos.
    const Queue visible(queue.begin(), queue.begin() + std::min(queue.size(), VISIBLE));
    ScoreLookahead lookahead{w, configs, std::min<size_t>(2, visible.size())};
    std::optional<Decision> best;
    walk(field, visible, 0, nullptr, configs.rules, configs.normal, best, nullptr, 0,
        nullptr, nullptr, true, true, &lookahead, configs.root_placements);
    if (lookahead.opening_main) best = lookahead.opening_main;
    else if (lookahead.opening_fallback) best = lookahead.opening_fallback;

    ScorePlan plan{{}, &search.candidates.front(), normal_scoring::pure(configs.score_fire_chain, *configs.normal),
        normal_scoring::pure(REPAIR_REFERENCE_CHAIN, *configs.normal)};
    if (!best || (best->chain.score <= 0 && !configs.score_preserve_main)) return plan;
    const int points = best->chain.score;
    // Once the known pieces can fire a full main, keep an executable route
    // to it. A higher score on the virtual bags can break a tie between
    // routes, but cannot replace the known trigger with a guessed color.
    const bool below_opening = best->chain.count < configs.score_opening_min_chain;
    const bool above_line = !below_opening && points >= plan.fire_line;
    plan.visible_fire_protected = !below_opening && (above_line ||
        (best->chain.count >= configs.score_reserve_chain && points >= normal_scoring::pure(configs.score_reserve_chain, *configs.normal)));
    // A visible fallback one link short of the fire line keeps its route while the opening builds on toward
    // the minimum, and is fired where no build keeps it: a 14 traded for the virtual queues' guess stalled at
    // 13 on a full board (2026-11-14 23:00 log, round 3 1P pair 34), where the 14-link minimum fired 14.
    const bool keep_fallback = below_opening && lookahead.opening_fallback
        && best->chain.count >= (configs.score_keep_fallback_chain > 0
            ? configs.score_keep_fallback_chain : configs.score_fire_chain - 1);
    if (below_opening && lookahead.opening_fallback) {
        // Pass a ready fallback only when the known pieces can still be stacked.
        if (best->moves == 1) {
            const auto extension = std::find_if(search.candidates.begin(), search.candidates.end(),
                [&](const Candidate& c) {
                    const auto& route = lookahead.at(c.placement);
                    return route.quiet_visible && (!keep_fallback || route.retained_points >= points);
                });
            if (extension != search.candidates.end()) plan.build = &*extension;
            else {
                plan.fire = best;
                plan.visible_fire_protected = true;
            }
            return plan;
        }
        // Keep the route to a capacity fire if its last piece cannot stack.
        const auto& capacity = lookahead.opening_capacity_fire;
        if (capacity && capacity->chain.score == points) {
            plan.fire = capacity;
            plan.visible_fire_protected = true;
            return plan;
        }
    }
    const int capacity = 4 * 13 + 2 * (11 - configs.rules.margin);
    const bool crowded = field.get_count() + piece::cell_count(queue.front().shape) >= capacity;
    if (configs.preserve_visible_fire && above_line) {
        plan.fire = best;
        return plan;
    }
    const Candidate* extension = nullptr;
    const Candidate* retaining = nullptr;
    const int held = (configs.score_preserve_main || configs.score_repair_damaged || configs.score_retain_main)
        ? potential(field, w, configs).near_chain : 0;

    for (const auto& candidate : search.candidates) {
        if (!builds_main(candidate)) continue;
        const auto& continuation = lookahead.at(candidate.placement);
        const bool retains = continuation.retained_points >= points;
        const bool grows = continuation.potential_points > points;
        plan.potential_points = std::max(plan.potential_points, continuation.potential_points);
        if (plan.visible_fire_protected && continuation.visible_points < points) continue;
        if (keep_fallback && !retains) continue;

        // A single-column shape estimate can miss a continuation that needs a
        // particular placement first. Keep the existing beam's preferred root
        // when several of its forecasts also justify waiting.
        const auto improving = std::count_if(candidate.projected.begin(), candidate.projected.end(),
            [points](i64 estimate) { return estimate > points; });
        const bool supported = &candidate == plan.build &&
            improving >= 2 && candidate.score > size_t(points) * VIRTUAL_COUNT;
        if (!((!above_line && !crowded) || supported || (retains && (!crowded || grows))
                || (grows && !crowded && candidate.next_room > 1))) continue;
        if (!extension) {
            extension = &candidate;
        }
        if ((configs.score_preserve_main || configs.score_retain_main) && !retaining && held >= 8
                && continuation.survives_visible && candidate.held_main >= held - 1)
            retaining = &candidate;
    }
    // The virtual queues are searched with every piece known, so a rebuild after burying the trigger
    // looks almost as good as the main the board holds (2026-11-14 log: 4 of 10 such rebuilds never
    // came back). Only a rebuild that wins on every queue by a wide margin may give the main up.
    const auto rebuild_dominates = [&](const Candidate& build, const Candidate& keeper) {
        const int percent = configs.score_retain_override_percent;
        if (configs.score_preserve_main || percent <= 0 || build.projected.size() != keeper.projected.size()
                || build.projected.empty()) return false;
        for (size_t i = 0; i < build.projected.size(); ++i)
            if (build.projected[i] <= keeper.projected[i]) return false;
        return build.score * 100 >= keeper.score * size_t(percent);
    };
    if (extension && retaining && extension->held_main <= held - 3 && !rebuild_dominates(*extension, *retaining))
        extension = retaining;
    if (extension) plan.build = extension;
    else if (points > 0) plan.fire = best;
    if (keep_fallback) plan.visible_fire_protected = true;
    if (!plan.visible_fire_protected) {
        consider_score_rebuild(field, queue, visible, search, character, index, w, configs, lookahead, points, plan);
        if (extension && !plan.fire && configs.score_repair && visible.size() >= 2
                && points < normal_scoring::pure(8, *configs.normal)
                && extension->projected.size() == VIRTUAL_COUNT) {
            for (const auto& repair : search.candidates) {
                const auto& route = lookahead.at(repair.placement);
                if (!route.repair_root || !route.survives_visible || repair.next_room <= 0
                        || repair.held_main < std::max(8, extension->held_main + 3)
                        || repair.held_main < held - 1 || repair.score <= extension->score
                        || repair.projected.size() != VIRTUAL_COUNT) continue;
                int improving = 0;
                for (size_t i = 0; i < VIRTUAL_COUNT; ++i)
                    improving += repair.projected[i] > extension->projected[i];
                if (improving > VIRTUAL_COUNT / 2) {
                    plan.build = &repair;
                    plan.repair = true;
                    break;
                }
            }
        }
        if (visible.size() >= 2)
            consider_damaged_repair(search, lookahead, held, *best, plan);
    }
    return plan;
}

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

    if (configs.construction_scoring || configs.maximize_score) configs.normal = normal_scoring::find(character.id);
    auto search = search_multi(field, queue, character, index, w, configs);

    // No placement survives
    if (search.candidates.empty()) {
        return {};
    }

    // The fire policy may take over
    const auto score = configs.maximize_score ?
        fire::score_plan(field, queue, search, character, index, w, configs) : fire::ScorePlan{};
    auto decision = configs.maximize_score ? score.fire : fire::decide(field, queue, search, configs);

    if (decision) {
        return Choice {
            .placement = decision->placement,
            .chain = decision->chain.count,
            .score = size_t(decision->chain.score),
            .fire = true,
            .fire_moves = decision->moves,
            .search_depths = search.virtual_depths,
            .fire_line_points = score.fire_line,
            .repair_line_points = score.repair_line,
            .build_potential_points = score.potential_points,
            .score_rebuild = score.rebuild,
            .visible_fire_protected = score.visible_fire_protected
        };
    }

    json reconstruction = nullptr;
    if (!configs.maximize_score) {
        if (configs.rebuild && !configs.aim && configs.stretch)
            reconstruction = rebuild::rank(field, queue, search, w, configs);
        std::stable_sort(search.candidates.begin(),search.candidates.end(),
            [&](const Candidate& a,const Candidate& b){
                if ((a.next_room>0)!=(b.next_room>0)) return a.next_room>0;
                return configs.sustained && a.throughput>b.throughput;
            });
    }
    auto chosen = configs.maximize_score ? score.build : &search.candidates.front();
    if (configs.preserve_build && !configs.maximize_score) {
        int held=0;
        for (const auto& c:search.candidates) if(c.next_room>0) held=std::max(held,c.held_main);
        const auto quiet = std::find_if(search.candidates.begin(), search.candidates.end(), [&](const Candidate& candidate) {
            auto next = field;
            const auto& move = candidate.placement;
            return candidate.next_room>0 && (!candidate.root_chain || held<5 || candidate.held_main>=held-1)
                && next.drop_piece(move.x, move.r, queue[0], configs.rules) && next.pop().get_size() <= 2;
        });
        if (quiet != search.candidates.end()) chosen = &*quiet;
    }
    auto& best = *chosen;

    json root_values = json::array();
    for (const auto& c : search.candidates) root_values.push_back({
        {"x",c.placement.x},{"r",std::string(1,"URDL"[int(c.placement.r)])},
        {"points",c.projected},{"next_room",c.next_room},{"held_main",c.held_main}});
    return Choice {
        .placement = best.placement,
        .chain = best.chain,
        .score = best.score / VIRTUAL_COUNT,
        .fire = false,
        .search_depths = search.virtual_depths,
        .reconstruction = reconstruction,
        .root_values = root_values,
        .fire_line_points = score.fire_line,
        .repair_line_points = score.repair_line,
        .build_potential_points = score.potential_points,
        .visible_fire_protected = score.visible_fire_protected,
        .score_repair = score.repair,
        .keep_main_clear = best.keeps_main && best.root_chain > 0
    };
};

};

#include "../ai/search/beam/beam.h"
#include <iostream>
#include <stdexcept>
#include <string_view>

static void check(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

static void column(Field& field, i8 x, std::string_view colors)
{
    for (i8 y = 0; y < i8(colors.size()); ++y) {
        field.set_cell(x, y, cell::from_char(colors[y]));
    }
}

struct Expanded
{
    beam::node::Data node;
    chain::Score chain;
};

// Exercise the real placement, pop and accounting path, retaining one legal move.
static Expanded expand_at(beam::node::Data parent, const cell::Pair& pair,
                          move::Placement placement, const beam::eval::Weight& weight)
{
    bool found = false;
    Expanded result;
    beam::expand(pair, parent, weight,
        [&](beam::node::Data& child, const move::Placement& move, const chain::Score& score) {
            if (move == placement) {
                found = true;
                result = {child, score};
            }
        });
    check(found, "safe clearing placement remains a legal search candidate");
    return result;
}

static beam::Candidate next_candidate(beam::node::Data parent, const cell::Pair& pair,
                                      const beam::eval::Weight& weight, i32 initial_clear = 0)
{
    parent.index = 0;
    beam::Layer parents(100), children(100);
    parents.data.push_back(parent);
    std::vector<beam::Candidate> candidates(1);
    candidates.front().clear_puyos = initial_clear;
    beam::think(pair, candidates, parents, children, weight);
    return candidates.front();
}

static beam::node::Data six_chain()
{
    beam::node::Data node;
    column(node.field, 0, "RR");
    column(node.field, 1, "RGGG");
    column(node.field, 2, "GBBB");
    column(node.field, 3, "BYYY");
    column(node.field, 4, "YRRRBG");
    column(node.field, 5, "RGGG");
    return node;
}

int main()
{
    try {
        // Every sampled tail must have the requested length, including odd
        // lengths; otherwise changing visible NEXT also changes search depth.
        for (i32 id = 0; id < i32(beam::BRANCH); ++id) {
            for (bool zoro : {false, true}) {
                auto full = beam::get_queue_random(id, 20, zoro);
                for (size_t count = 0; count <= 20; ++count) {
                    auto tail = beam::get_queue_random(id, count, zoro, true);
                    check(tail.size() == count, "sampled queue respects the requested horizon");
                    check(std::equal(tail.begin(), tail.end(), full.begin()), "sampling preserves the queue prefix");
                    auto legacy_tail = beam::get_queue_random(id, count, zoro);
                    check(legacy_tail.size() == count + (count % 2),
                          "default sampling retains the production horizon");
                }
            }
        }
        beam::eval::Weight weight;
        json legacy = weight;
        legacy.erase("clear_cost");
        weight.clear_cost = 400;
        legacy.get_to(weight);
        check(weight.clear_cost == 0, "legacy weights disable clearing cost");
        json enabled = legacy;
        enabled["clear_cost"] = 400;
        enabled.get_to(weight);
        check(weight.clear_cost == 400, "clearing cost loads from JSON");
        check(json(weight).at("clear_cost") == 400, "clearing cost survives JSON round trip");

        const cell::Pair red_yellow{cell::Type::RED, cell::Type::YELLOW};
        const cell::Pair red_red{cell::Type::RED, cell::Type::RED};

        beam::node::Data four;
        column(four.field, 0, "RRR");
        auto cleared_four = expand_at(four, red_yellow, {0, direction::Type::UP}, weight);
        check(cleared_four.chain.count == 1 && cleared_four.chain.score == 40,
              "four-puyo fixture clears one ordinary link");
        check(cleared_four.node.cleared == 4, "four colored puyos are charged");

        beam::node::Data eight;
        column(eight.field, 0, "RR");
        column(eight.field, 1, "R");
        column(eight.field, 4, "R");
        column(eight.field, 5, "RR");
        auto cleared_eight = expand_at(eight, red_red, {2, direction::Type::RIGHT}, weight);
        check(cleared_eight.chain.count == 1, "eight-puyo fixture also clears only one link");
        check(cleared_eight.node.cleared == 8, "eight-puyo single clear costs twice as many resources");
        check(cleared_eight.node.field.is_empty(), "a safe all clear is still generated");

        auto with_garbage = four;
        column(with_garbage.field, 1, "#");
        auto cleaned = expand_at(with_garbage, red_yellow, {0, direction::Type::UP}, weight);
        check(cleaned.node.cleared == 4, "removing adjacent garbage is not charged as a colored resource");
        check(cleaned.node.field.data[u8(cell::Type::GARBAGE)].is_empty(), "garbage really was removed");

        auto direct = six_chain();
        auto fired = expand_at(direct, red_yellow, {0, direction::Type::UP}, weight);
        check(fired.chain.count == 6 && fired.chain.score == 8680, "fixture fires a six-chain worth 8680");
        auto direct_candidate = next_candidate(direct, red_yellow, weight);
        check(direct_candidate.score == 8680 && direct_candidate.utility == 8680,
              "the firing chain itself is not charged a clearing cost");

        // A real legal single clear followed by the same six-chain. The first
        // move removes four yellow puyos above the tail and leaves the chain.
        auto needs_cleanup = six_chain();
        column(needs_cleanup.field, 5, "RGGGYYY");
        auto cleanup = expand_at(needs_cleanup, {cell::Type::YELLOW, cell::Type::BLUE},
                                 {5, direction::Type::UP}, weight);
        check(cleanup.chain.count == 1 && cleanup.node.cleared == 4,
              "preparation really performs a four-puyo single clear");
        auto prepared_fire = expand_at(cleanup.node, red_yellow, {0, direction::Type::UP}, weight);
        check(prepared_fire.chain.count == 6 && prepared_fire.chain.score == 8680,
              "the small clear leaves the main chain fireable");
        check(prepared_fire.node.cleared == 28, "colored clearing count accumulates across placements");
        auto new_decision = next_candidate(cleanup.node, red_yellow, weight);
        check(new_decision.score == 8680 && new_decision.utility == 8680,
              "already-spent clears are not charged again in a new decision");
        auto prepared_candidate = next_candidate(cleanup.node, red_yellow, weight, 4);
        check(prepared_candidate.score == 8680, "an initial small clear never reduces raw chain score");
        check(prepared_candidate.utility == 8680 - 4 * 400,
              "candidate utility charges the known initial small clear once");

        auto more_cleanup = cleanup.node;
        more_cleanup.cleared = 8;
        check(beam::node::get_hash(cleanup.node) == beam::node::get_hash(more_cleanup),
              "future clearing history preserves legacy table sharing");
        auto more_cost = next_candidate(more_cleanup, red_yellow, weight, 8);
        check(more_cost.score == prepared_candidate.score && more_cost.utility == 8680 - 8 * 400,
              "equal future chains distinguish four from eight puyos cleared by the initial move");
        more_cleanup.cleared = 100;
        auto historical = next_candidate(more_cleanup, red_yellow, weight, 4);
        check(historical.utility == prepared_candidate.utility,
              "later or historical clears do not add to the initial-move utility charge");
        auto exhausted = next_candidate(more_cleanup, red_yellow, weight, 100);
        check(exhausted.score == 8680 && exhausted.utility == 0,
              "large clearing costs saturate utility without unsigned underflow or deleting raw score");

        auto waiting = expand_at(needs_cleanup, red_red,
                                 {1, direction::Type::UP}, weight);
        check(waiting.chain.count == 0, "future-cleanup path starts with a non-clearing placement");
        auto future_cleanup = expand_at(waiting.node, {cell::Type::YELLOW, cell::Type::BLUE},
                                        {5, direction::Type::UP}, weight);
        check(future_cleanup.chain.count == 1 && future_cleanup.node.cleared == 4,
              "the later path really includes a small clear");
        auto future_fire = expand_at(future_cleanup.node, red_yellow, {0, direction::Type::UP}, weight);
        check(future_fire.chain.score >= beam::PRUNE, "the future small clear still permits a main chain");
        auto future_candidate = next_candidate(future_cleanup.node, red_yellow, weight);
        check(future_candidate.score >= size_t(future_fire.chain.score) &&
              future_candidate.utility == future_candidate.score,
              "a future small clear after a non-clearing first move does not reduce utility");

        beam::Configs two_moves;
        two_moves.width = 100;
        two_moves.depth = 2;
        two_moves.target = 8000;
        const cell::Queue visible = {{cell::Type::YELLOW, cell::Type::BLUE}, red_yellow};
        auto sampled = beam::search_multi(needs_cleanup.field, visible, weight, two_moves);
        bool cleanup_found = false;
        for (const auto& candidate : sampled.candidates) {
            if (candidate.placement == move::Placement{5, direction::Type::UP}) {
                cleanup_found = true;
                check(candidate.score == 8680 * beam::BRANCH,
                      "multi-queue search accumulates unchanged raw chain scores");
                check(candidate.utility == (8680 - 4 * 400) * beam::BRANCH,
                      "multi-queue search retains the root cleanup cost in candidate utility");
                check(candidate.clear_puyos == 4, "known initial resources are not multiplied by queue count");
                check(candidate.reach == beam::BRANCH,
                      "target reach uses raw points even when utility is below the target");
            }
        }
        check(cleanup_found, "a small clear enabling the main chain remains available in full search");

        auto small_only = beam::search(four.field,
            {red_yellow, {cell::Type::GREEN, cell::Type::BLUE}}, weight, two_moves);
        bool small_found = false;
        for (const auto& candidate : small_only.candidates) {
            if (candidate.placement == move::Placement{0, direction::Type::UP}) {
                small_found = true;
                check(candidate.score == 40 && candidate.utility == 0 && candidate.clear_puyos == 4,
                      "an immediate small-clear score also pays its known initial cost");
            }
        }
        check(small_found, "a safe initial small clear remains available even with zero utility");

        auto main_now = beam::search(direct.field,
            {red_yellow, {cell::Type::YELLOW, cell::Type::BLUE}}, weight, two_moves);
        bool main_found = false;
        for (const auto& candidate : main_now.candidates) {
            if (candidate.placement == move::Placement{0, direction::Type::UP}) {
                main_found = true;
                check(candidate.score == 8680 && candidate.utility == 8680 && candidate.clear_puyos == 0,
                      "an initial main-chain fire is exempt from the small-clear cost");
            }
        }
        check(main_found, "immediate main-chain fire remains available");

        weight.clear_cost = 0;
        auto disabled = next_candidate(cleanup.node, red_yellow, weight, 4);
        check(disabled.utility == disabled.score && disabled.score == 8680,
              "disabled cost preserves the original score ranking");
        auto disabled_clear = expand_at(four, red_yellow, {0, direction::Type::UP}, weight);
        check(disabled_clear.node.cleared == 0, "disabled cost leaves legacy resource accounting untouched");
        weight.clear_cost = -400;
        auto negative = next_candidate(cleanup.node, red_yellow, weight, 4);
        check(negative.utility == negative.score, "negative configured cost cannot reward repeated clearing");

        beam::Configs configs;
        check(beam::compare(direct_candidate, prepared_candidate, configs),
              "equal raw chains prefer a first move that does not spend puyos on a small clear");
        auto larger_but_wasteful = prepared_candidate;
        larger_but_wasteful.score = 9000;
        check(beam::compare(direct_candidate, larger_but_wasteful, configs),
              "utility affects final candidate ranking instead of only beam pruning");
        auto clean_tie = prepared_candidate;
        clean_tie.clear_puyos = 0;
        clean_tie.score = 8000;
        check(beam::compare(clean_tie, prepared_candidate, configs),
              "equal utility prefers fewer known initial clears before comparing raw score");
        auto tie = direct_candidate;
        tie.score += 1;
        check(beam::compare(tie, direct_candidate, configs), "raw score breaks equal-utility ties");
        configs.target = 8000;
        prepared_candidate.reach = 1;
        direct_candidate.reach = 0;
        check(beam::compare(prepared_candidate, direct_candidate, configs),
              "explicit raw-score target reach remains the primary criterion");

        configs.target = 0;
        configs.stretch = false;
        beam::Candidate enough_small, enough_large, below_trigger;
        enough_small.score = 140000 * beam::BRANCH;
        enough_small.utility = 1000 * beam::BRANCH;
        enough_large.score = 150000 * beam::BRANCH;
        enough_large.utility = 100000 * beam::BRANCH;
        below_trigger.score = 129000 * beam::BRANCH;
        below_trigger.utility = 50000 * beam::BRANCH;
        check(beam::compare(enough_small, enough_large, configs),
              "non-stretch still prefers the smaller sufficient chain");
        check(beam::compare(enough_large, below_trigger, configs) &&
              beam::compare(enough_small, below_trigger, configs) &&
              !beam::compare(below_trigger, enough_small, configs),
              "non-stretch ordering stays transitive across the raw firing threshold");

        std::cout << "Chain quality checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

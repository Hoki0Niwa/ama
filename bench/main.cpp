#include "../ai/ai.h"
#include "../puyop/encode.h"
#include <fstream>

// Batch benchmark for comparing evaluation weights
// Plays one game per seed with the same rules as the puyop client:
// - 100 moves at most
// - stops at the first chain >= 78000
// Appends one line per seed to a TSV file:
// seed, result (fired / dead / nomove / timeout), score of the first chain >= 78000 (0 if none),
// biggest chain score, biggest chain length, moves played, frames spent, wall time in ms,
// longest search of the game in ms,
// then, for the chain that ended the game (all 0 when the game did not fire):
// count_fire (puyos in the field just before it popped, triggering pair included),
// popped (puyos it removed), leftover (count_fire - popped), excess (popped - 4 * links),
// max_link (most puyos removed by a single link), wasted (puyos popped by the chains fired before it)
// then, for every game (including non-firing games):
// small_clear_moves (moves that cleared a chain before the ending chain), single_clear_moves (one-link subset),
// first_130k_move (1-based move on which the current pair could first fire >= 130000, -1 if never),
// fire_delay_130k (ending fire move minus first_130k_move, -1 if never ready or did not fire)
// The AI sees ai::QUEUE_VISIBLE pairs and plays through the fire policy like the real client
// BEAM_WIDTH, BEAM_DEPTH, BEAM_TRIGGER, BEAM_TARGET and BEAM_ZORO (0/1) in the environment override the beam
// search configuration, FIRE_GUARD (0/1), FIRE_GUARD_FIRE (0/1), FIRE_GUARD_COUNT, FIRE_GUARD_SCORE,
// FIRE_GUARD_KEEP and FIRE_PANIC_COUNT the fire policy,
// QUEUE_VISIBLE (2..128, capped at BEAM_DEPTH) the number of known pairs, including the current pair
// Optionally appends one line per seed (seed, result, score, puyop.com URL that replays every move played)
// to a URL file
// Optionally appends the field of each game to a snapshot file (see `write_snapshot`),
// which `render.py` turns into an image to compare the shapes built with different weights
// Writes the field as text, from the 14th row down to the 1st row, using the same characters as Field::print
// The field is the one just before the chain popped: for a fired game it shows the complete chain with the
// triggering pair placed, otherwise the last position reached
void write_snapshot(std::ofstream& out, u32 seed, const char* result, i32 score, i32 moves, Field& field)
{
    out << "# seed " << seed << " result " << result << " score " << score << " moves " << moves << '\n';

    for (i8 x = 0; x < 6; ++x) {
        out << ((field.row14 >> x) & 1 ? '#' : '.');
    }

    out << '\n';

    for (i8 y = 12; y >= 0; --y) {
        for (i8 x = 0; x < 6; ++x) {
            out << cell::to_char(field.get_cell(x, y));
        }

        out << '\n';
    }

    out.flush();
};

// Observe whether the current pair can fire 130k without changing the move the AI chose.
// Use the same legal placements and survival check as the fire policy.
bool can_fire_130k(Field field, const cell::Pair& pair)
{
    auto locks = move::generate(field, pair.first == pair.second);

    for (auto i = 0; i < locks.get_size(); ++i) {
        auto next = field;
        next.drop_pair(locks[i].x, locks[i].r, pair);
        auto pop = next.pop();

        if (next.get_height(2) <= 11 && chain::get_score(pop).score >= 130000) {
            return true;
        }
    }

    return false;
};

int main(int argc, char** argv)
{
    if (argc < 5) {
        fprintf(stderr, "usage: bench <weight.json> <seed_begin> <seed_end> <out.tsv> [max_moves=100] [snapshot.txt] [urls.txt]\n");
        fprintf(stderr, "environment: BEAM_WIDTH, BEAM_DEPTH, BEAM_TRIGGER, BEAM_TARGET, BEAM_ZORO (0/1) override the beam search configuration, "
                        "FIRE_GUARD (0/1), FIRE_GUARD_FIRE (0/1), FIRE_GUARD_COUNT, FIRE_GUARD_SCORE, FIRE_GUARD_KEEP, FIRE_PANIC_COUNT the fire policy, "
                        "QUEUE_VISIBLE the known pairs shown (2..128, including current, capped at beam depth)\n");
        fprintf(stderr, "tsv columns: seed result score max_score max_count moves frames ms ms_max "
                        "count_fire popped leftover excess max_link wasted "
                        "small_clear_moves single_clear_moves first_130k_move fire_delay_130k\n");
        fprintf(stderr, "<weight.json> is one flat weight set, e.g. the \"build\" object of config.json\n");
        return 1;
    }

    beam::eval::Weight w;
    {
        std::ifstream file(argv[1]);

        if (!file.good()) {
            fprintf(stderr, "can't open \"%s\"\n", argv[1]);
            return 1;
        }

        json js;
        file >> js;
        from_json(js, w);
    }

    u32 seed_begin = u32(atoi(argv[2]));
    u32 seed_end = u32(atoi(argv[3]));
    i32 max_moves = argc > 5 ? atoi(argv[5]) : 100;

    std::ofstream out(argv[4], std::ios::app);

    // Beam search configuration, overridable from the environment for experiments
    auto configs = beam::Configs();
    configs.exact_depth = true;

    if (getenv("BEAM_WIDTH") != nullptr) {
        configs.width = size_t(atoi(getenv("BEAM_WIDTH")));
    }

    if (getenv("BEAM_DEPTH") != nullptr) {
        configs.depth = size_t(atoi(getenv("BEAM_DEPTH")));
    }

    if (getenv("BEAM_TRIGGER") != nullptr) {
        configs.trigger = size_t(atoi(getenv("BEAM_TRIGGER")));
    }

    if (getenv("BEAM_TARGET") != nullptr) {
        configs.target = size_t(atoi(getenv("BEAM_TARGET")));
    }

    if (getenv("BEAM_ZORO") != nullptr) {
        configs.zoro = atoi(getenv("BEAM_ZORO")) != 0;
    }

    // Fire policy, overridable from the environment for experiments
    auto policy = ai::fire::Policy();

    if (getenv("FIRE_GUARD") != nullptr) {
        policy.guard = atoi(getenv("FIRE_GUARD")) != 0;
    }

    if (getenv("FIRE_GUARD_FIRE") != nullptr) {
        policy.guard_fire = atoi(getenv("FIRE_GUARD_FIRE")) != 0;
    }

    if (getenv("FIRE_GUARD_COUNT") != nullptr) {
        policy.guard_count = i32(atoi(getenv("FIRE_GUARD_COUNT")));
    }

    if (getenv("FIRE_GUARD_SCORE") != nullptr) {
        policy.guard_score = i32(atoi(getenv("FIRE_GUARD_SCORE")));
    }

    if (getenv("FIRE_GUARD_KEEP") != nullptr) {
        policy.guard_keep = i32(atoi(getenv("FIRE_GUARD_KEEP")));
    }

    if (getenv("FIRE_PANIC_COUNT") != nullptr) {
        policy.panic_count = i32(atoi(getenv("FIRE_PANIC_COUNT")));
    }

    // Known pairs, including the current pair. Do not search beyond the fixed
    // horizon merely because more of the future queue was supplied.
    size_t visible = ai::QUEUE_VISIBLE;

    if (getenv("QUEUE_VISIBLE") != nullptr) {
        visible = size_t(std::clamp(atoi(getenv("QUEUE_VISIBLE")), 2, 128));
    }
    visible = std::min(visible, configs.depth);

    std::ofstream snapshot;

    if (argc > 6) {
        snapshot.open(argv[6], std::ios::app);
    }

    std::ofstream urls;

    if (argc > 7) {
        urls.open(argv[7], std::ios::app);
    }

    for (u32 seed = seed_begin; seed < seed_end; ++seed) {
        Field field;
        auto queue = cell::create_queue(seed);

        i32 score = 0;
        i32 max_score = 0;
        i32 max_count = 0;
        i32 moves = 0;

        // Every pair played with its placement, for the puyop URL
        std::vector<cell::Pair> played_pairs;
        std::vector<move::Placement> played;
        i32 frames = 0;
        const char* result = "timeout";
        i64 ms_max = 0;

        // Chain efficiency of the chain that ended the game
        i32 count_fire = 0;
        i32 popped = 0;
        i32 max_link = 0;
        i32 wasted = 0;
        i32 links = 0;
        i32 small_clear_moves = 0;
        i32 single_clear_moves = 0;
        i32 first_130k_move = -1;

        // Field just before the last pop
        Field snap = field;

        auto t0 = std::chrono::steady_clock::now();

        for (i32 i = 0; i < max_moves; ++i) {
            cell::Queue q;

            for (size_t k = 0; k < visible; ++k) {
                q.push_back(queue[(i + k) % 128]);
            }

            snap = field;

            auto t1 = std::chrono::steady_clock::now();

            auto ai = q.size() >= configs.depth
                ? beam::search(field, q, w, configs)
                : beam::search_multi(field, q, w, configs);
            if (q.size() >= configs.depth) {
                std::sort(ai.candidates.begin(), ai.candidates.end(),
                    [&](const auto& a, const auto& b) { return beam::compare(a, b, configs); });
            }

            // No placement survives
            if (ai.candidates.empty()) {
                result = "nomove";
                break;
            }

            auto mv = ai.candidates.front();

            // The fire policy may take over when the field is nearly full
            auto decision = ai::fire::decide(field, q, ai, i32(configs.trigger), policy);

            if (decision.has_value()) {
                mv.placement = decision->placement;
            }

            ms_max = std::max(ms_max, std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t1).count());

            // Keep this diagnostic outside the search timing and stop scanning once it is known.
            if (first_130k_move < 0 && can_fire_130k(field, q[0])) {
                first_130k_move = moves + 1;
            }

            played_pairs.push_back(q[0]);
            played.push_back(mv.placement);

            frames += field.get_drop_pair_frame(mv.placement.x, mv.placement.r);
            field.drop_pair(mv.placement.x, mv.placement.r, q[0]);

            snap = field;

            auto mask = field.pop();

            // Puyos popped by this chain, before get_score consumes the mask
            i32 chain_popped = 0;
            i32 chain_max_link = 0;

            for (i32 k = 0; k < mask.get_size(); ++k) {
                i32 n = i32(mask[k].get_count());
                chain_popped += n;
                chain_max_link = std::max(chain_max_link, n);
            }

            auto chain = chain::get_score(mask);
            moves += 1;

            if (chain.score > max_score) {
                max_score = chain.score;
                max_count = chain.count;
            }

            if (field.get_height(2) > 11) {
                result = "dead";
                break;
            }

            if (chain.score >= 78000) {
                score = chain.score;
                result = "fired";
                count_fire = i32(snap.get_count());
                popped = chain_popped;
                links = chain.count;
                max_link = chain_max_link;
                break;
            }

            wasted += chain_popped;
            small_clear_moves += chain.count > 0;
            single_clear_moves += chain.count == 1;
            frames += chain.count * 2;
        }

        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();

        out << seed << '\t' << result << '\t' << score << '\t' << max_score << '\t' << max_count
            << '\t' << moves << '\t' << frames << '\t' << ms << '\t' << ms_max
            << '\t' << count_fire << '\t' << popped << '\t' << (count_fire - popped)
            << '\t' << (popped - 4 * links) << '\t' << max_link << '\t' << (links > 0 ? wasted : 0)
            << '\t' << small_clear_moves << '\t' << single_clear_moves << '\t' << first_130k_move
            << '\t' << (links > 0 && first_130k_move > 0 ? moves - first_130k_move : -1) << '\n';
        out.flush();

        if (urls.is_open()) {
            urls << seed << '\t' << result << '\t' << score << '\t' << encode::get_encoded_URL(Field(), played_pairs, played) << '\n';
            urls.flush();
        }

        if (snapshot.is_open()) {
            write_snapshot(snapshot, seed, result, score, moves, snap);
        }

        printf("seed %u: %s %d (%d moves)\n", seed, result, score, moves);
    }

    return 0;
};

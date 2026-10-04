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
// longest search of the game in ms
// The AI sees ai::QUEUE_VISIBLE pairs and plays through the fire policy like the real client
// BEAM_WIDTH, BEAM_DEPTH and BEAM_TRIGGER in the environment override the beam search configuration,
// QUEUE_VISIBLE (2 or 3) the number of pairs shown to the AI
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

int main(int argc, char** argv)
{
    if (argc < 5) {
        fprintf(stderr, "usage: bench <weight.json> <seed_begin> <seed_end> <out.tsv> [max_moves=100] [snapshot.txt] [urls.txt]\n");
        fprintf(stderr, "environment: BEAM_WIDTH, BEAM_DEPTH, BEAM_TRIGGER override the beam search configuration, QUEUE_VISIBLE the pairs shown (2 or 3)\n");
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

    if (getenv("BEAM_WIDTH") != nullptr) {
        configs.width = size_t(atoi(getenv("BEAM_WIDTH")));
    }

    if (getenv("BEAM_DEPTH") != nullptr) {
        configs.depth = size_t(atoi(getenv("BEAM_DEPTH")));
    }

    if (getenv("BEAM_TRIGGER") != nullptr) {
        configs.trigger = size_t(atoi(getenv("BEAM_TRIGGER")));
    }

    // Pairs shown to the AI, to compare against fewer visible pairs
    size_t visible = ai::QUEUE_VISIBLE;

    if (getenv("QUEUE_VISIBLE") != nullptr) {
        visible = std::clamp(size_t(atoi(getenv("QUEUE_VISIBLE"))), size_t(2), ai::QUEUE_VISIBLE);
    }

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

            auto ai = beam::search_multi(field, q, w, configs);

            // No placement survives
            if (ai.candidates.empty()) {
                result = "nomove";
                break;
            }

            auto mv = ai.candidates.front();

            // The fire policy may take over when the field is nearly full
            auto decision = ai::fire::decide(field, q, ai, i32(configs.trigger));

            if (decision.has_value()) {
                mv.placement = decision->placement;
            }

            ms_max = std::max(ms_max, std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t1).count());

            played_pairs.push_back(q[0]);
            played.push_back(mv.placement);

            frames += field.get_drop_pair_frame(mv.placement.x, mv.placement.r);
            field.drop_pair(mv.placement.x, mv.placement.r, q[0]);

            snap = field;

            auto mask = field.pop();
            auto chain = chain::get_score(mask);
            moves += 1;

            if (chain.score > max_score) {
                max_score = chain.score;
                max_count = chain.count;
            }

            if (field.is_dead(rule::TSU)) {
                result = "dead";
                break;
            }

            if (chain.score >= 78000) {
                score = chain.score;
                result = "fired";
                break;
            }

            frames += chain.count * 2;
        }

        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();

        out << seed << '\t' << result << '\t' << score << '\t' << max_score << '\t' << max_count
            << '\t' << moves << '\t' << frames << '\t' << ms << '\t' << ms_max << '\n';
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

#include "../ai/ai.h"
#include <fstream>

// Batch benchmark for comparing evaluation weights
// Plays one game per seed with the same rules as the puyop client:
// - 100 moves at most
// - stops at the first chain >= 78000
// Appends one line per seed to a TSV file:
// seed, result (fired / dead / nomove / timeout), score of the first chain >= 78000 (0 if none),
// biggest chain score, biggest chain length, moves played, frames spent, wall time in ms
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
        fprintf(stderr, "usage: bench <weight.json> <seed_begin> <seed_end> <out.tsv> [max_moves=100] [snapshot.txt]\n");
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

    std::ofstream snapshot;

    if (argc > 6) {
        snapshot.open(argv[6], std::ios::app);
    }

    for (u32 seed = seed_begin; seed < seed_end; ++seed) {
        Field field;
        auto queue = cell::create_queue(seed);

        i32 score = 0;
        i32 max_score = 0;
        i32 max_count = 0;
        i32 moves = 0;
        i32 frames = 0;
        const char* result = "timeout";

        // Field just before the last pop
        Field snap = field;

        auto t0 = std::chrono::steady_clock::now();

        for (i32 i = 0; i < max_moves; ++i) {
            cell::Queue q = { queue[(i + 0) % 128], queue[(i + 1) % 128] };

            snap = field;

            auto ai = beam::search_multi(field, q, w);

            // No placement survives
            if (ai.candidates.empty()) {
                result = "nomove";
                break;
            }

            auto mv = ai.candidates.front();

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

            if (field.get_height(2) > 11) {
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
            << '\t' << moves << '\t' << frames << '\t' << ms << '\n';
        out.flush();

        if (snapshot.is_open()) {
            write_snapshot(snapshot, seed, result, score, moves, snap);
        }

        printf("seed %u: %s %d (%d moves)\n", seed, result, score, moves);
    }

    return 0;
};

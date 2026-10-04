#include "../fever/fire.h"
#include "../fever/text.h"

// Batch benchmark of solo chain building under the fever rule, the counterpart of `bench`
// Plays one game per seed:
// - 100 moves at most
// - stops at the first chain of BENCH_GOAL links or more (10 by default)
// Appends one line per seed to a TSV file:
// character, seed, result (fired / dead / nomove / timeout), score of the first chain that reached the goal
// (0 if none), biggest chain score, longest chain, moves played, frames spent, wall time in ms,
// longest search of the game in ms, cells dealt, cells discarded above the 13th row,
// number of small chains (1 to 3 links) popped
// The scores use the Tsu table and the frames are the abstract 1/2 costs of the search: neither is the
// real game's value yet (stage B). The chain lengths are exact for the modelled rules.
// The colors come from fever::create_queue, which does NOT reproduce the Steam version's color generation.
// The AI sees QUEUE_VISIBLE pieces (3 by default) and plays through the fire policy
// BEAM_WIDTH, BEAM_DEPTH and BEAM_TRIGGER (a chain length) in the environment override the search configuration
// Optionally appends the field of each game to a snapshot file that `bench/render.py` reads
// Optionally appends one JSON line per move played to a log file, to replay a game
void write_snapshot(std::ofstream& out, u32 seed, const char* result, i32 score, i32 moves, Field& field)
{
    out << "# seed " << seed << " result " << result << " score " << score << " moves " << moves << '\n';

    for (auto& row : fever::text::from_field(field)) {
        out << row << '\n';
    }

    out.flush();
};

int main(int argc, char** argv)
{
    if (argc < 6) {
        fprintf(stderr, "usage: bench_fever <weight.json> <character> <seed_begin> <seed_end> <out.tsv> [max_moves=100] [snapshot.txt] [moves.jsonl]\n");
        fprintf(stderr, "environment: BEAM_WIDTH, BEAM_DEPTH, BEAM_TRIGGER (chain length), BENCH_GOAL (chain length), QUEUE_VISIBLE\n");
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

    const auto* character = dropset::find(argv[2]);

    if (character == nullptr || !dropset::drop_at(*character, 0)) {
        fprintf(stderr, "unknown character or cycle \"%s\"\n", argv[2]);
        return 1;
    }

    u32 seed_begin = u32(atoi(argv[3]));
    u32 seed_end = u32(atoi(argv[4]));
    i32 max_moves = argc > 6 ? atoi(argv[6]) : 100;

    std::ofstream out(argv[5], std::ios::app);

    auto env = [] (const char* name, i32 value) {
        return getenv(name) != nullptr ? atoi(getenv(name)) : value;
    };

    auto configs = fever::Configs();

    configs.width = size_t(env("BEAM_WIDTH", i32(configs.width)));
    configs.depth = size_t(env("BEAM_DEPTH", i32(configs.depth)));
    configs.trigger = env("BEAM_TRIGGER", configs.trigger);

    i32 goal = env("BENCH_GOAL", 10);
    size_t visible = size_t(std::clamp(env("QUEUE_VISIBLE", 3), 1, 3));

    std::ofstream snapshot;

    if (argc > 7) {
        snapshot.open(argv[7], std::ios::app);
    }

    std::ofstream log;

    if (argc > 8) {
        log.open(argv[8], std::ios::app);
    }

    for (u32 seed = seed_begin; seed < seed_end; ++seed) {
        Field field;

        // The whole game's pieces. The AI is only ever handed the visible ones.
        auto queue = fever::create_queue(*character, seed, size_t(max_moves) + visible);

        if (!queue) {
            fprintf(stderr, "can't create the queue of \"%s\"\n", argv[2]);
            return 1;
        }

        i32 score = 0;
        i32 max_score = 0;
        i32 max_count = 0;
        i32 moves = 0;
        i32 frames = 0;
        i32 cells = 0;
        i32 discarded = 0;
        i32 small = 0;
        const char* result = "timeout";
        i64 ms_max = 0;

        // Field just before the last pop
        Field snap = field;

        auto t0 = std::chrono::steady_clock::now();

        for (i32 i = 0; i < max_moves; ++i) {
            fever::Queue q(queue->begin() + i, queue->begin() + i + visible);

            auto t1 = std::chrono::steady_clock::now();

            auto choice = fever::think(field, q, *character, u64(i), w, configs);

            ms_max = std::max(ms_max, std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t1).count());

            // No placement survives
            if (!choice) {
                result = "nomove";
                break;
            }

            auto frame = field.get_drop_piece_frame(choice->placement.x, choice->placement.r, q[0], configs.rules);
            auto drop = field.drop_piece(choice->placement.x, choice->placement.r, q[0], configs.rules);

            if (!frame || !drop) {
                fprintf(stderr, "seed %u move %d: the search returned an illegal placement\n", seed, i);
                return 1;
            }

            frames += *frame;
            cells += i32(piece::cell_count(q[0].shape));
            discarded += drop->discarded;

            snap = field;

            auto mask = field.pop();
            auto chain = chain::get_score(mask);
            moves += 1;

            if (chain.count >= 1 && chain.count <= 3) {
                small += 1;
            }

            if (chain.count > max_count || (chain.count == max_count && chain.score > max_score)) {
                max_score = chain.score;
                max_count = chain.count;
            }

            bool dead = field.is_dead(configs.rules);

            if (log.is_open()) {
                json js;

                js["character"] = std::string(character->id);
                js["seed"] = seed;
                js["move"] = moves;
                js["dropset_index"] = i;
                js["piece"] = fever::text::from_piece(q[0]);
                js["x"] = choice->placement.x;
                js["r"] = std::string(1, fever::text::from_direction(choice->placement.r));
                js["fire"] = choice->fire;
                js["expected_chain"] = choice->chain;
                js["chain"] = chain.count;
                js["score"] = chain.score;
                js["discarded"] = drop->discarded;
                js["dead"] = dead;
                js["placed"] = fever::text::from_field(snap);
                js["field"] = fever::text::from_field(field);

                log << js.dump() << '\n';
            }

            if (dead) {
                result = "dead";
                break;
            }

            if (chain.count >= goal) {
                score = chain.score;
                result = "fired";
                break;
            }

            frames += chain.count * 2;
        }

        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();

        out << character->id << '\t' << seed << '\t' << result << '\t' << score << '\t' << max_score << '\t' << max_count
            << '\t' << moves << '\t' << frames << '\t' << ms << '\t' << ms_max
            << '\t' << cells << '\t' << discarded << '\t' << small << '\n';
        out.flush();

        if (log.is_open()) {
            log.flush();
        }

        if (snapshot.is_open()) {
            write_snapshot(snapshot, seed, result, score, moves, snap);
        }

        printf("%s seed %u: %s %d chain (%d moves)\n", character->id.data(), seed, result, max_count, moves);
    }

    return 0;
};

#include "../ai/ai.h"
#include "../ai/path.h"
#include <fstream>
#include <sstream>
#include <memory>
#include <exception>

#ifdef _WIN32
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#else
#include <unistd.h>
#include <fcntl.h>
#include <sys/wait.h>
#include <signal.h>
#endif

// PVP simulation between two engines
//
// The default referee jumps between events in virtual game frames (see TIMING.md).
// --timing abstract retains the original pair=1, chain link=2 referee.
// Both players share the same queue, as in Puyo Puyo Tsu.
// Nuisance is computed from the chain score with `target_point` points per puyo (70 in Tsu),
// offset against the nuisance pending on the attacker, sent to the opponent when the chain ends and
// dropped (at most 30 at a time) after the next pair the opponent places without starting a chain,
// so the opponent can still offset it with that pair. An all clear adds 30 puyos to the next chain.
// A player loses when the 3rd column reaches the 12th row or no placement survives.
//
// An engine is either in-process (`local` or `local:config.json`) or any command line that runs the
// JSON line protocol below, e.g. another build of this program started with `--engine`. This is how
// two different versions of the AI can be matched against each other.
//
// Protocol (one JSON object per line):
//   request:  { "self": player, "enemy": player, "target_point": 70, "trigger": 100000, "stretch": true }
//   player:   { "field": [14 strings, 14th row first, same characters as Field::print],
//               "queue": ["RG", "BY", "YY"], "all_clear": false, "bonus": 0, "attack": 0,
//               "attack_chain": 0, "attack_frame": 0, "dropping": 0 }
//   reply:    { "x": 2, "r": "U", "eval": 0, "trigger": null }

namespace pvp
{

constexpr i32 TARGET_POINT = 70;
constexpr i32 ALL_CLEAR_BONUS = 30;
constexpr i32 GARBAGE_DROP_MAX = 30;
constexpr i32 QUEUE_VISIBLE = 3;

// How the referee drives the AI's `trigger` and `stretch` arguments, which the game client normally sets:
// the AI keeps stretching its chain while the field holds fewer than STRETCH_LIMIT puyos, then fires
// as soon as a chain worth the trigger is available, and the trigger is lowered when the field gets
// dangerously full so the AI fires what it has instead of overflowing
// A 16 chain, the smallest worth the trigger, needs about 64 puyos, so the limits leave room for it;
// the AI's own fire policy (ai/fire.h) handles the danger zone before these kick in
constexpr i32 STRETCH_LIMIT = 60;
constexpr i32 PANIC_LIMIT_1 = 70;
constexpr i32 PANIC_TRIGGER_1 = 78000;
constexpr i32 PANIC_LIMIT_2 = 74;
constexpr i32 PANIC_TRIGGER_2 = 10000;

#include "protocol.h"
#include "engine.h"

// Serves the JSON line protocol on stdin/stdout
int serve(const std::string& config_path)
{
    LocalEngine engine(config_path);

    std::string line;

    while (std::getline(std::cin, line))
    {
        if (line.empty()) {
            continue;
        }

        auto input = json::parse(line);
        auto request = request_from_json(input);
        bool solo = input.value("solo", false);
        i32 attack_score = 0;
        i32 attack_chain = 0;
        const auto started = std::chrono::steady_clock::now();
        std::optional<Reply> fire_choice;
        auto reply = solo
            ? engine.think_solo(request, input.value("fire", false), attack_score, attack_chain, &fire_choice)
            : engine.think(request);

        auto enrich = [&](const Reply& reply) {
        auto output = reply_to_json(reply);
        if (reply.build_required) {
            output["build_required"] = true;
            return output;
        }
        if (solo) {
            output["solo"] = true;
            output["attack_score"] = attack_score;
            output["attack_chain"] = attack_chain;
        }
        if (input.value("include_path", false)) {
            // Export the fork's own spawn-based route, without changing its AI.
            // Finder::find appends DROP even for an unreachable target; distinguish
            // that case explicitly instead of sending an accidental straight drop.
            auto& field = request.self.field;
            u8 heights[6];
            field.get_heights(heights);
            auto p = reply.placement;
            bool valid = move::is_valid(heights, field.row14, p.x, p.r)
                && !field.is_colliding_pair(2, 11, direction::Type::UP, heights);
            path::Queue route;
            if (valid && !(p.x == 2 && p.r == direction::Type::UP)) {
                auto map = path::Finder::generate_placements(field, p, request.self.queue[0]);
                route = map.get(p.x, p.r);
                valid = !route.empty();
            }
            output["path"] = json::array();
            output["path_origin"] = "spawn";
            output["path_reachable"] = valid;
            if (valid) {
                route = path::Finder::get_queue_convert_m180(route);
                route.push_back(path::Input::DROP);
                for (auto key : route) {
                    switch (key) {
                    case path::Input::LEFT: output["path"].push_back("LEFT"); break;
                    case path::Input::RIGHT: output["path"].push_back("RIGHT"); break;
                    case path::Input::CW: output["path"].push_back("CW"); break;
                    case path::Input::CCW: output["path"].push_back("CCW"); break;
                    case path::Input::NONE: output["path"].push_back("NONE"); break;
                    case path::Input::DROP: output["path"].push_back("DROP"); break;
                    default: throw std::runtime_error("Unsupported path input");
                    }
                }
            }
        }
        if (input.value("include_next", false)) {
            // The field once this reply's placement has landed and every chain has resolved,
            // so a caller can start thinking about the following pair while this one is still moving.
            auto after = request.self.field;
            u8 after_heights[6];
            after.get_heights(after_heights);
            auto q = reply.placement;
            if (move::is_valid(after_heights, after.row14, q.x, q.r)) {
                after.drop_pair(q.x, q.r, request.self.queue[0]);
                auto mask = after.pop();
                auto chain = chain::get_score(mask);
                output["next_chain"] = chain.count;
                output["next_score"] = chain.score;
                output["next_all_clear"] = after.is_empty();
                output["next_field"] = field_to_rows(after);
            }
        }
        return output;
        };
        auto output = enrich(reply);
        if (!solo) {
            output["search_reusable"] = true;
            output["search_reused"] = engine.search_reused;
            output["build_search"] = engine.build_search;
        }
        if (fire_choice && !input.value("fire", false)) output["fire_reply"] = enrich(*fire_choice);
        output["search_ms"] = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
        printf("%s\n", output.dump().c_str());
        fflush(stdout);
    }

    return 0;
};

#include "timing.h"

// Nuisance that has been sent but hasn't landed yet
struct Incoming
{
    i32 count = 0;
    i32 arrive = 0;
};

struct Player
{
    Field field = Field();
    i32 queue_index = 0;
    i32 moves = 0;
    i32 free_at = 0;       // tick when the player can place the next pair
    i32 chain_end = 0;     // tick when the running chain ends
    i32 chain_count = 0;   // links of the running chain
    i32 bonus = 0;         // score remainder carried to the next chain
    bool all_clear = false;
    i32 trigger = ai::TRIGGER;
    i32 tray = 0;          // nuisance that has landed and drops before the next pair
    std::vector<Incoming> incoming;
    i32 max_chain = 0;
    i32 max_score = 0;
    i32 sent = 0;
    i32 received = 0;

    i32 incoming_total()
    {
        i32 total = this->tray;

        for (auto& in : this->incoming) {
            total += in.count;
        }

        return total;
    };

    // Moves nuisance whose sender's chain has ended into the tray
    void settle(i32 now)
    {
        std::vector<Incoming> remain;

        for (auto& in : this->incoming) {
            if (in.arrive <= now) {
                this->tray += in.count;
            }
            else {
                remain.push_back(in);
            }
        }

        this->incoming = remain;
    };

    // Offsets nuisance with the player's own chain, returns what is left to send
    i32 offset(i32 count)
    {
        i32 cancel = std::min(count, this->tray);
        this->tray -= cancel;
        count -= cancel;

        for (auto& in : this->incoming) {
            cancel = std::min(count, in.count);
            in.count -= cancel;
            count -= cancel;
        }

        return count;
    };
};

struct GameResult
{
    i32 winner = -1;       // 0, 1 or -1 for a draw
    std::string reason;
    i32 moves[2] = { 0, 0 };
    i32 max_chain[2] = { 0, 0 };
    i32 max_score[2] = { 0, 0 };
    i32 sent[2] = { 0, 0 };
    i32 ticks = 0;
    Field field[2];
};

struct Options
{
    i32 games = 10;
    u32 seed = 1;
    i32 target_point = TARGET_POINT;
    i32 max_moves = 300;
    bool verbose = false;
    std::string log;
    bool frames = true;
    i32 jobs = 1;
    size_t beam_width = 250;
    size_t beam_depth = 16;
    Timing timing;
};

GameResult play_abstract(Engine* engines[2], u32 seed, i32 first, const Options& options, std::ostream& log)
{
    auto queue = cell::create_queue(seed);

    Player players[2];
    GameResult result;

    auto pairs_at = [&] (i32 index) {
        cell::Queue q;

        for (i32 i = 0; i < QUEUE_VISIBLE; ++i) {
            q.push_back(queue[(index + i) % 128]);
        }

        return q;
    };

    auto finish = [&] (i32 winner, const char* reason, i32 ticks) {
        result.winner = winner;
        result.reason = reason;
        result.ticks = ticks;

        for (i32 i = 0; i < 2; ++i) {
            result.moves[i] = players[i].moves;
            result.max_chain[i] = players[i].max_chain;
            result.max_score[i] = players[i].max_score;
            result.sent[i] = players[i].sent;
            result.field[i] = players[i].field;
        }

        return result;
    };

    while (true)
    {
        // The player who is free first moves, the starting player on ties
        i32 p = first;

        if (players[1 - first].free_at < players[first].free_at) {
            p = 1 - first;
        }

        i32 o = 1 - p;
        i32 now = players[p].free_at;

        auto& self = players[p];
        auto& enemy = players[o];

        if (self.moves >= options.max_moves && enemy.moves >= options.max_moves) {
            return finish(-1, "max_moves", now);
        }

        self.settle(now);
        enemy.settle(now);

        // Builds the request
        auto view = [&] (Player& me, Player& other) {
            gaze::Player view;

            view.field = me.field;
            view.queue = pairs_at(me.queue_index);
            view.all_clear = me.all_clear;
            view.bonus = me.bonus + (me.all_clear ? ALL_CLEAR_BONUS * options.target_point : 0);
            view.attack = other.incoming_total();
            view.attack_chain = me.chain_count;
            view.attack_frame = std::max(0, me.chain_end - now);
            view.dropping = (me.chain_end <= now) ? me.tray : 0;

            return view;
        };

        Request request;

        request.self = view(self, enemy);
        request.enemy = view(enemy, self);
        request.target_point = options.target_point;
        request.beam_width = options.beam_width;
        request.beam_depth = options.beam_depth;

        i32 count = self.field.get_count();

        request.trigger = self.trigger;
        request.stretch = count < STRETCH_LIMIT;

        if (count >= PANIC_LIMIT_2) {
            request.trigger = std::min(request.trigger, PANIC_TRIGGER_2);
        }
        else if (count >= PANIC_LIMIT_1) {
            request.trigger = std::min(request.trigger, PANIC_TRIGGER_1);
        }

        auto reply = engines[p]->think(request);

        self.trigger = reply.trigger.value_or(ai::TRIGGER);

        // Logs the decision as one JSON line per move
        if (!options.log.empty()) {
            json js = request_to_json(request);

            js["game_seed"] = seed;
            js["player"] = p == 0 ? "A" : "B";
            js["tick"] = now;
            js["move"] = self.moves + 1;
            js["reply"] = reply_to_json(reply);

            log << js.dump() << '\n';
        }

        // Applies the placement
        auto pair = queue[self.queue_index % 128];

        u8 heights[6];
        self.field.get_heights(heights);

        if (!move::is_valid(heights, self.field.row14, reply.placement.x, reply.placement.r)) {
            return finish(o, "no_move", now);
        }

        i32 cost = self.field.get_drop_pair_frame(reply.placement.x, reply.placement.r);

        self.field.drop_pair(reply.placement.x, reply.placement.r, pair);
        self.queue_index += 1;
        self.moves += 1;

        auto mask = self.field.pop();
        auto chain = chain::get_score(mask);

        if (!options.log.empty() && chain.count > 0) {
            json js;

            js["game_seed"] = seed;
            js["player"] = p == 0 ? "A" : "B";
            js["tick"] = now;
            js["move"] = self.moves;
            js["chain"] = chain.count;
            js["score"] = chain.score;

            log << js.dump() << '\n';
        }

        self.free_at = now + cost;

        if (chain.count > 0) {
            i32 total = chain.score + self.bonus;

            if (self.all_clear) {
                total += ALL_CLEAR_BONUS * options.target_point;
                self.all_clear = false;
            }

            i32 nuisance = total / options.target_point;
            self.bonus = total % options.target_point;

            self.chain_count = chain.count;
            self.chain_end = self.free_at + chain.count * 2;
            self.free_at = self.chain_end;

            nuisance = self.offset(nuisance);

            if (nuisance > 0) {
                enemy.incoming.push_back(Incoming { .count = nuisance, .arrive = self.chain_end });
                self.sent += nuisance;
            }

            if (self.field.is_empty()) {
                self.all_clear = true;
            }

            self.max_chain = std::max(self.max_chain, chain.count);
            self.max_score = std::max(self.max_score, chain.score);
        }

        if (self.field.get_height(2) > 11) {
            return finish(o, "death", self.free_at);
        }

        // Nuisance that has landed drops after a pair that didn't start a chain
        if (chain.count == 0) {
            self.settle(self.free_at);

            if (self.tray > 0) {
                i32 drop = std::min(self.tray, GARBAGE_DROP_MAX);

                self.field.drop_garbage(drop);
                self.tray -= drop;
                self.received += drop;
                self.free_at += 1;

                if (self.field.get_height(2) > 11) {
                    return finish(o, "garbage", self.free_at);
                }
            }
        }
    }
};

#include "simulator.h"

void print_field_pair(Field& a, Field& b)
{
    auto ra = field_to_rows(a);
    auto rb = field_to_rows(b);

    for (size_t i = 0; i < ra.size(); ++i) {
        printf("  %s    %s\n", ra[i].c_str(), rb[i].c_str());
    }
};

int match(const std::string& spec_a, const std::string& spec_b, const Options& options)
{
    i32 wins[2] = { 0, 0 };
    i32 draws = 0;

    std::ofstream log;

    if (!options.log.empty()) {
        log.open(options.log);
        if (!log) throw std::runtime_error("can't open match log: " + options.log);
        log << json({{"event", "match"}, {"timing", options.frames ? "frames" : "abstract"},
            {"profile", options.timing.to_json()}, {"beam_width", options.beam_width},
            {"beam_depth", options.beam_depth}, {"jobs", options.jobs},
            {"seed", options.seed}, {"games", options.games},
            {"max_moves", options.max_moves}, {"target_point", options.target_point},
            {"engine_A", spec_a}, {"engine_B", spec_b}}).dump() << '\n';
    }

    printf("A: %s\nB: %s\n", spec_a.c_str(), spec_b.c_str());
    printf("games: %d, first seed: %u, target point: %d\n\n", options.games, options.seed, options.target_point);
    printf("timing: %s, beam: %zux%zu, jobs: %d\n", options.frames ? "frames" : "abstract", options.beam_width, options.beam_depth, options.jobs);
    printf("game\tseed\twinner\treason\tticks\tmoves_A\tmoves_B\tchain_A\tchain_B\tsent_A\tsent_B\n");
    fflush(stdout);

    struct Completed { GameResult result; double seconds = 0; std::string log; bool done = false; };
    std::vector<Completed> completed(options.games);
    std::atomic<i32> next_game = 0;
    std::mutex mutex;
    std::condition_variable changed;
    std::exception_ptr failure;
    std::atomic<bool> stop = false;
    auto match_start = std::chrono::steady_clock::now();
    std::vector<std::jthread> workers;
    for (i32 worker = 0; worker < std::min(options.jobs, options.games); ++worker) {
        workers.emplace_back([&] {
            try {
                // Never share an engine's cache or a process pipe across matches.
                auto a = make_engine(spec_a); auto b = make_engine(spec_b);
                Engine* engines[2] = {a.get(), b.get()};
                while (!stop) {
                    i32 g = next_game.fetch_add(1);
                    if (g >= options.games) break;
                    std::ostringstream game_log;
                    auto start = std::chrono::steady_clock::now();
                    auto result = play(engines, options.seed + u32(g), g % 2, options, game_log);
                    double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
                    {
                        std::lock_guard<std::mutex> lock(mutex);
                        completed[g] = {result, seconds, game_log.str(), true};
                    }
                    changed.notify_one();
                }
            }
            catch (...) {
                std::lock_guard<std::mutex> lock(mutex);
                if (!failure) failure = std::current_exception();
                stop = true;
                changed.notify_one();
            }
        });
    }

    i64 total_frames = 0;
    for (i32 g = 0; g < options.games; ++g) {
        u32 seed = options.seed + u32(g);
        Completed game;
        {
            std::unique_lock<std::mutex> lock(mutex);
            changed.wait(lock, [&] { return completed[g].done || failure; });
            if (failure) break;
            game = std::move(completed[g]);
        }
        auto& result = game.result;
        total_frames += result.ticks;
        if (log.is_open()) log << game.log;

        const char* winner = result.winner == 0 ? "A" : (result.winner == 1 ? "B" : "draw");

        if (result.winner >= 0) {
            wins[result.winner] += 1;
        }
        else {
            draws += 1;
        }

        printf("%d\t%u\t%s\t%s\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t(%.3fs)\n",
            g + 1, seed, winner, result.reason.c_str(), result.ticks,
            result.moves[0], result.moves[1],
            result.max_chain[0], result.max_chain[1],
            result.sent[0], result.sent[1],
            game.seconds);

        if (options.verbose) {
            printf("  A                 B\n");
            print_field_pair(result.field[0], result.field[1]);
            printf("\n");
        }

        fflush(stdout);
    }

    workers.clear(); // join before reading the failure or destroying shared state
    if (failure) std::rethrow_exception(failure);
    printf("\nA wins: %d, B wins: %d, draws: %d\n", wins[0], wins[1], draws);
    double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - match_start).count();
    printf("wall: %.3fs, games/s: %.3f", elapsed, options.games / std::max(0.000001, elapsed));
    if (options.frames) printf(", simulated seconds: %.3f, speed: %.2fx", double(total_frames) / options.timing.fps, total_frames / (options.timing.fps * std::max(0.000001, elapsed)));
    printf("\n");

    return 0;
};

};

int main(int argc, char** argv)
{
    using namespace pvp;
    try {

    std::vector<std::string> args(argv + 1, argv + argc);

    if (!args.empty() && args[0] == "--engine") {
        return serve(args.size() > 1 ? args[1] : "config.json");
    }

    Options options;
    std::vector<std::string> specs;

    for (size_t i = 0; i < args.size(); ++i) {
        auto next = [&] () -> std::string {
            if (i + 1 >= args.size()) {
                fprintf(stderr, "missing value for %s\n", args[i].c_str());
                exit(1);
            }

            return args[++i];
        };

        if (args[i] == "--games") {
            options.games = std::stoi(next());
        }
        else if (args[i] == "--seed") {
            options.seed = u32(std::stoul(next()));
        }
        else if (args[i] == "--target") {
            options.target_point = std::stoi(next());
        }
        else if (args[i] == "--max-moves") {
            options.max_moves = std::stoi(next());
        }
        else if (args[i] == "--verbose") {
            options.verbose = true;
        }
        else if (args[i] == "--log") {
            options.log = next();
        }
        else if (args[i] == "--timing") {
            auto mode = next();
            if (mode != "frames" && mode != "abstract") throw std::runtime_error("--timing must be frames or abstract");
            options.frames = mode == "frames";
        }
        else if (args[i] == "--timing-config") {
            options.timing.load(next());
        }
        else if (args[i] == "--jobs") {
            options.jobs = std::stoi(next());
        }
        else if (args[i] == "--beam-width") {
            auto value = std::stoi(next());
            if (value <= 0 || value > 100000) throw std::runtime_error("--beam-width must be in 1..100000");
            options.beam_width = size_t(value);
        }
        else if (args[i] == "--beam-depth") {
            auto value = std::stoi(next());
            if (value < 2 || value > 128) throw std::runtime_error("--beam-depth must be in 2..128");
            options.beam_depth = size_t(value);
        }
        else if (args[i] == "--fast") {
            options.beam_width = 50; options.beam_depth = 8;
        }
        else if (args[i].starts_with("--")) {
            throw std::runtime_error("unknown option: " + args[i]);
        }
        else {
            specs.push_back(args[i]);
        }
    }

    if (specs.size() != 2) {
        fprintf(stderr,
            "usage: pvp [--games N] [--seed S] [--target P] [--max-moves M] [--verbose] [--log moves.jsonl]\n"
            "           [--timing frames|abstract] [--timing-config profile.json] [--jobs N]\n"
            "           [--fast | --beam-width W --beam-depth D] <engine A> <engine B>\n"
            "       pvp --engine [config.json]\n"
            "an engine is `local`, `local:<config.json>` or a command line that speaks the engine protocol\n");
        return 1;
    }

    if (options.games <= 0 || options.max_moves <= 0 || options.target_point <= 0 || options.jobs <= 0 || options.jobs > 256)
        throw std::runtime_error("games, max-moves and target must be positive; jobs must be in 1..256");
    return match(specs[0], specs[1], options);
    }
    catch (const std::exception& error) {
        fprintf(stderr, "pvp: %s\n", error.what());
        return 1;
    }
};

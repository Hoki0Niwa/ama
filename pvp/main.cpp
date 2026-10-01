#include "../ai/ai.h"
#include <fstream>
#include <sstream>
#include <memory>

#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#include <sys/wait.h>
#include <signal.h>
#endif

// PVP simulation between two engines
//
// Time is counted in the same abstract unit the AI uses: placing a pair costs 1 (2 when the pair
// tears apart) and every chain link costs 2. Both players share the same queue, as in Puyo Puyo Tsu.
// Nuisance is computed from the chain score with `target_point` points per puyo (70 in Tsu),
// offset against the nuisance pending on the attacker, sent to the opponent when the chain ends and
// dropped (at most 30 at a time) before the opponent's next pair. An all clear adds 30 puyos to the
// next chain. A player loses when the 3rd column reaches the 12th row or no placement survives.
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

// Loads the nested config.json into the 4 weight sets
void load_configs(search::Configs& configs, const std::string& path)
{
    std::ifstream file(path);

    if (!file.good()) {
        fprintf(stderr, "can't open \"%s\"\n", path.c_str());
        exit(1);
    }

    json js;
    file >> js;

    js.at("build").get_to(configs.build);
    js.at("freestyle").get_to(configs.freestyle);
    js.at("fast").get_to(configs.fast);
    js.at("ac").get_to(configs.ac);
};

// Field <-> 14 text rows (14th row first)
std::vector<std::string> field_to_rows(Field& field)
{
    std::vector<std::string> rows;

    std::string row14;

    for (i8 x = 0; x < 6; ++x) {
        row14 += ((field.row14 >> x) & 1) ? '#' : '.';
    }

    rows.push_back(row14);

    for (i8 y = 12; y >= 0; --y) {
        std::string row;

        for (i8 x = 0; x < 6; ++x) {
            row += cell::to_char(field.get_cell(x, y));
        }

        rows.push_back(row);
    }

    return rows;
};

Field field_from_rows(const std::vector<std::string>& rows)
{
    char c[13][7] = { 0 };

    for (i32 y = 0; y < 13; ++y) {
        for (i32 x = 0; x < 6; ++x) {
            c[y][x] = rows[y + 1][x];
        }

        c[y][6] = 0;
    }

    Field field;
    field.from(c);

    field.row14 = 0;

    for (i32 x = 0; x < 6; ++x) {
        if (rows[0][x] == '#') {
            field.row14 |= 1 << x;
        }
    }

    return field;
};

char direction_to_char(direction::Type r)
{
    switch (r)
    {
    case direction::Type::UP:
        return 'U';
    case direction::Type::RIGHT:
        return 'R';
    case direction::Type::DOWN:
        return 'D';
    case direction::Type::LEFT:
        return 'L';
    }

    return 'U';
};

direction::Type direction_from_char(char c)
{
    switch (c)
    {
    case 'U':
        return direction::Type::UP;
    case 'R':
        return direction::Type::RIGHT;
    case 'D':
        return direction::Type::DOWN;
    case 'L':
        return direction::Type::LEFT;
    }

    return direction::Type::UP;
};

json player_to_json(gaze::Player& player)
{
    json js;

    js["field"] = field_to_rows(player.field);

    std::vector<std::string> queue;

    for (auto& pair : player.queue) {
        queue.push_back(std::string() + cell::to_char(pair.first) + cell::to_char(pair.second));
    }

    js["queue"] = queue;
    js["all_clear"] = player.all_clear;
    js["bonus"] = player.bonus;
    js["attack"] = player.attack;
    js["attack_chain"] = player.attack_chain;
    js["attack_frame"] = player.attack_frame;
    js["dropping"] = player.dropping;

    return js;
};

gaze::Player player_from_json(const json& js)
{
    gaze::Player player;

    player.field = field_from_rows(js.at("field").get<std::vector<std::string>>());

    for (auto& pair : js.at("queue").get<std::vector<std::string>>()) {
        player.queue.push_back({ cell::from_char(pair[0]), cell::from_char(pair[1]) });
    }

    player.all_clear = js.at("all_clear").get<bool>();
    player.bonus = js.at("bonus").get<i32>();
    player.attack = js.at("attack").get<i32>();
    player.attack_chain = js.at("attack_chain").get<i32>();
    player.attack_frame = js.at("attack_frame").get<i32>();
    player.dropping = js.at("dropping").get<i32>();

    return player;
};

struct Request
{
    gaze::Player self;
    gaze::Player enemy;
    i32 target_point = TARGET_POINT;
    i32 trigger = ai::TRIGGER;
    bool stretch = true;
};

struct Reply
{
    move::Placement placement;
    i32 eval = 0;
    std::optional<i32> trigger = {};
};

json request_to_json(Request& request)
{
    json js;

    js["self"] = player_to_json(request.self);
    js["enemy"] = player_to_json(request.enemy);
    js["target_point"] = request.target_point;
    js["trigger"] = request.trigger;
    js["stretch"] = request.stretch;

    return js;
};

Request request_from_json(const json& js)
{
    Request request;

    request.self = player_from_json(js.at("self"));
    request.enemy = player_from_json(js.at("enemy"));
    request.target_point = js.at("target_point").get<i32>();
    request.trigger = js.at("trigger").get<i32>();
    request.stretch = js.at("stretch").get<bool>();

    return request;
};

json reply_to_json(const Reply& reply)
{
    json js;

    js["x"] = reply.placement.x;
    js["r"] = std::string(1, direction_to_char(reply.placement.r));
    js["eval"] = reply.eval;

    if (reply.trigger.has_value()) {
        js["trigger"] = reply.trigger.value();
    }
    else {
        js["trigger"] = nullptr;
    }

    return js;
};

Reply reply_from_json(const json& js)
{
    Reply reply;

    reply.placement.x = js.at("x").get<i32>();
    reply.placement.r = direction_from_char(js.at("r").get<std::string>()[0]);
    reply.eval = js.at("eval").get<i32>();

    if (!js.at("trigger").is_null()) {
        reply.trigger = js.at("trigger").get<i32>();
    }

    return reply;
};

// An engine answers a request with a placement
class Engine
{
public:
    virtual ~Engine() {};
    virtual Reply think(Request& request) = 0;
    virtual std::string name() = 0;
};

// Runs the AI of this build in-process
class LocalEngine : public Engine
{
private:
    search::Configs configs;
    std::string config_path;
public:
    LocalEngine(const std::string& config_path) : config_path(config_path)
    {
        load_configs(this->configs, config_path);
    };
public:
    Reply think(Request& request) override
    {
        // The search normally runs while the previous pair is moving; here it runs synchronously
        search::Thread thread;

        thread.search(
            request.self.field,
            { request.self.queue[0], request.self.queue[1] },
            this->configs,
            request.trigger,
            request.stretch
        );

        auto bsearch = thread.get().value_or(search::Result());

        auto result = ai::think(
            request.self,
            request.enemy,
            bsearch,
            this->configs,
            request.target_point,
            ai::style::Data(),
            request.trigger,
            request.stretch
        );

        return Reply {
            .placement = result.placement,
            .eval = result.eval,
            .trigger = result.update.trigger
        };
    };

    std::string name() override
    {
        return "local:" + this->config_path;
    };
};

// Talks to another process over its stdin/stdout
class PipeEngine : public Engine
{
private:
    std::string command;
    FILE* to_child = nullptr;
    FILE* from_child = nullptr;
#ifdef _WIN32
    PROCESS_INFORMATION process = { 0 };
#else
    pid_t pid = -1;
#endif
public:
    PipeEngine(const std::string& command) : command(command)
    {
#ifdef _WIN32
        SECURITY_ATTRIBUTES sa = { sizeof(SECURITY_ATTRIBUTES), NULL, TRUE };

        HANDLE child_in_r, child_in_w, child_out_r, child_out_w;

        if (!CreatePipe(&child_in_r, &child_in_w, &sa, 0) || !CreatePipe(&child_out_r, &child_out_w, &sa, 0)) {
            fprintf(stderr, "can't create pipes\n");
            exit(1);
        }

        SetHandleInformation(child_in_w, HANDLE_FLAG_INHERIT, 0);
        SetHandleInformation(child_out_r, HANDLE_FLAG_INHERIT, 0);

        STARTUPINFOA si = { 0 };
        si.cb = sizeof(si);
        si.dwFlags = STARTF_USESTDHANDLES;
        si.hStdInput = child_in_r;
        si.hStdOutput = child_out_w;
        si.hStdError = GetStdHandle(STD_ERROR_HANDLE);

        std::string cmd = this->command;

        if (!CreateProcessA(NULL, cmd.data(), NULL, NULL, TRUE, 0, NULL, NULL, &si, &this->process)) {
            fprintf(stderr, "can't start \"%s\"\n", this->command.c_str());
            exit(1);
        }

        CloseHandle(child_in_r);
        CloseHandle(child_out_w);

        this->to_child = _fdopen(_open_osfhandle((intptr_t)child_in_w, 0), "w");
        this->from_child = _fdopen(_open_osfhandle((intptr_t)child_out_r, 0), "r");
#else
        int in[2], out[2];

        if (pipe(in) != 0 || pipe(out) != 0) {
            fprintf(stderr, "can't create pipes\n");
            exit(1);
        }

        this->pid = fork();

        if (this->pid < 0) {
            fprintf(stderr, "can't fork\n");
            exit(1);
        }

        if (this->pid == 0) {
            dup2(in[0], STDIN_FILENO);
            dup2(out[1], STDOUT_FILENO);
            close(in[0]); close(in[1]); close(out[0]); close(out[1]);
            execl("/bin/sh", "sh", "-c", this->command.c_str(), (char*)NULL);
            _exit(127);
        }

        close(in[0]);
        close(out[1]);

        this->to_child = fdopen(in[1], "w");
        this->from_child = fdopen(out[0], "r");
#endif
    };

    ~PipeEngine()
    {
        if (this->to_child != nullptr) {
            fclose(this->to_child);
        }

        if (this->from_child != nullptr) {
            fclose(this->from_child);
        }

#ifdef _WIN32
        WaitForSingleObject(this->process.hProcess, 5000);
        CloseHandle(this->process.hProcess);
        CloseHandle(this->process.hThread);
#else
        if (this->pid > 0) {
            waitpid(this->pid, NULL, 0);
        }
#endif
    };
public:
    Reply think(Request& request) override
    {
        auto line = request_to_json(request).dump();

        fprintf(this->to_child, "%s\n", line.c_str());
        fflush(this->to_child);

        std::string answer;
        char buffer[4096];

        while (true)
        {
            if (fgets(buffer, sizeof(buffer), this->from_child) == NULL) {
                fprintf(stderr, "engine \"%s\" closed its output\n", this->command.c_str());
                exit(1);
            }

            answer += buffer;

            if (!answer.empty() && answer.back() == '\n') {
                break;
            }
        }

        return reply_from_json(json::parse(answer));
    };

    std::string name() override
    {
        return this->command;
    };
};

std::unique_ptr<Engine> make_engine(const std::string& spec)
{
    if (spec == "local") {
        return std::make_unique<LocalEngine>("config.json");
    }

    if (spec.rfind("local:", 0) == 0) {
        return std::make_unique<LocalEngine>(spec.substr(6));
    }

    return std::make_unique<PipeEngine>(spec);
};

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

        auto request = request_from_json(json::parse(line));
        auto reply = engine.think(request);

        printf("%s\n", reply_to_json(reply).dump().c_str());
        fflush(stdout);
    }

    return 0;
};

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
};

GameResult play(Engine* engines[2], u32 seed, i32 first, const Options& options)
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

        // Nuisance drops before the next pair
        self.settle(now);

        if (self.tray > 0) {
            i32 drop = std::min(self.tray, GARBAGE_DROP_MAX);

            self.field.drop_garbage(drop);
            self.tray -= drop;
            self.received += drop;
            self.free_at += 1;
            now = self.free_at;

            if (self.field.get_height(2) > 11) {
                return finish(o, "garbage", now);
            }
        }

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
        request.trigger = self.trigger;
        request.stretch = true;

        auto reply = engines[p]->think(request);

        self.trigger = reply.trigger.value_or(ai::TRIGGER);

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
    }
};

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
    auto engine_a = make_engine(spec_a);
    auto engine_b = make_engine(spec_b);

    Engine* engines[2] = { engine_a.get(), engine_b.get() };

    i32 wins[2] = { 0, 0 };
    i32 draws = 0;

    printf("A: %s\nB: %s\n", engine_a->name().c_str(), engine_b->name().c_str());
    printf("games: %d, first seed: %u, target point: %d\n\n", options.games, options.seed, options.target_point);
    printf("game\tseed\twinner\treason\tticks\tmoves_A\tmoves_B\tchain_A\tchain_B\tsent_A\tsent_B\n");

    for (i32 g = 0; g < options.games; ++g) {
        u32 seed = options.seed + u32(g);
        i32 first = g % 2;

        auto t0 = std::chrono::steady_clock::now();
        auto result = play(engines, seed, first, options);
        auto secs = std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now() - t0).count();

        const char* winner = result.winner == 0 ? "A" : (result.winner == 1 ? "B" : "draw");

        if (result.winner >= 0) {
            wins[result.winner] += 1;
        }
        else {
            draws += 1;
        }

        printf("%d\t%u\t%s\t%s\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t(%llds)\n",
            g + 1, seed, winner, result.reason.c_str(), result.ticks,
            result.moves[0], result.moves[1],
            result.max_chain[0], result.max_chain[1],
            result.sent[0], result.sent[1],
            (long long)secs);

        if (options.verbose) {
            printf("  A                 B\n");
            print_field_pair(result.field[0], result.field[1]);
            printf("\n");
        }

        fflush(stdout);
    }

    printf("\nA wins: %d, B wins: %d, draws: %d\n", wins[0], wins[1], draws);

    return 0;
};

};

int main(int argc, char** argv)
{
    using namespace pvp;

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
        else {
            specs.push_back(args[i]);
        }
    }

    if (specs.size() != 2) {
        fprintf(stderr,
            "usage: pvp [--games N] [--seed S] [--target P] [--max-moves M] [--verbose] <engine A> <engine B>\n"
            "       pvp --engine [config.json]\n"
            "an engine is `local`, `local:<config.json>` or a command line that speaks the engine protocol\n");
        return 1;
    }

    return match(specs[0], specs[1], options);
};

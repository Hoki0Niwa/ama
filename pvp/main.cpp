#include "../ai/ai.h"
#include "../ai/path.h"
#include <fstream>
#include <sstream>
#include <memory>

#ifdef _WIN32
#include <windows.h>
#include <io.h>
#include <fcntl.h>
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
    // Beam search size. The defaults are the original constants; a smaller beam trades a little depth for speed.
    size_t beam_width = 250;
    size_t beam_depth = 16;
    size_t attack_pairs = ai::QUEUE_VISIBLE;      // pairs the one-player attack search looks through
    bool reuse_search = false;
    size_t search_prefix = 0;                    // prefetch: the trailing guessed pair may change
    bool tactics_only = false;                  // defer an unprepared beam before the client releases DOWN
};

struct Reply
{
    move::Placement placement;
    i32 eval = 0;
    std::optional<i32> trigger = {};
    std::vector<move::Placement> alternatives;
    bool build_required = false;
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
    request.beam_width = js.value("beam_width", request.beam_width);
    request.beam_depth = js.value("beam_depth", request.beam_depth);
    request.attack_pairs = std::clamp(js.value("attack_pairs", request.attack_pairs), size_t(1), size_t(ai::QUEUE_VISIBLE));
    request.reuse_search = js.value("reuse_search", false);
    request.search_prefix = js.value("search_prefix", size_t(0));
    request.tactics_only = js.value("tactics_only", false);

    return request;
};

json reply_to_json(const Reply& reply)
{
    json js;

    js["x"] = reply.placement.x;
    js["r"] = std::string(1, direction_to_char(reply.placement.r));
    js["eval"] = reply.eval;
    if (!reply.alternatives.empty()) {
        js["alternatives"] = json::array();
        for (auto& p : reply.alternatives) {
            js["alternatives"].push_back({{"x", p.x}, {"r", std::string(1, direction_to_char(p.r))}});
        }
    }

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
    std::optional<Request> prepared_for;
    search::Result prepared;
    bool prepared_types[4] = {false, false, false, false};
    struct BuildRequired {};
public:
    bool search_reused = false;
    std::string build_search = "none";
    LocalEngine(const std::string& config_path) : config_path(config_path)
    {
        load_configs(this->configs, config_path);
    };
public:
    Reply think(Request& request) override
    {
        // Keep construction separate from the opponent's animation and nuisance gauges.
        // Re-evaluate tactics against the live request while retaining the early build.
        auto matches = [&] {
            if (!request.reuse_search || !prepared_for) return false;
            auto& old = *prepared_for;
            auto count = request.search_prefix ? request.search_prefix : request.self.queue.size();
            return old.self.field == request.self.field
                && old.self.queue.size() == request.self.queue.size()
                && count <= request.self.queue.size()
                && count >= std::min(size_t(2), request.self.queue.size())
                && std::equal(request.self.queue.begin(), request.self.queue.begin() + count, old.self.queue.begin())
                && old.trigger == request.trigger && old.stretch == request.stretch
                && old.beam_width == request.beam_width && old.beam_depth == request.beam_depth;
        };
        search_reused = matches();
        build_search = "none";
        if (!search_reused) {
            prepared_for = request;
            prepared = search::Result();
            std::fill(std::begin(prepared_types), std::end(prepared_types), false);
        }

        auto prepare = [&](search::Type type, search::Result& results) {
            if (!prepared_types[type]) {
                if (type == search::Type::BUILD) {
                    if (request.tactics_only) throw BuildRequired();
                    search::Thread thread;
                    thread.search(request.self.field, request.self.queue, configs, request.trigger,
                                  request.stretch, request.beam_width, request.beam_depth);
                    prepared = thread.get().value_or(search::Result());
                    std::fill(std::begin(prepared_types), std::end(prepared_types), true);
                    build_search = "beam";
                }
                else {
                    cell::Queue q2 = {request.self.queue[0], request.self.queue[1]};
                    if (type == search::Type::FAST) {
                        prepared.fast = dfs::build::search(request.self.field, q2, configs.fast);
                        build_search = "fast";
                    }
                    else if (type == search::Type::AC) {
                        prepared.ac = dfs::build::search(request.self.field, q2, configs.ac);
                        build_search = "ac";
                    }
                    else {
                        prepared.freestyle = dfs::build::search(request.self.field, q2, configs.freestyle);
                        build_search = "freestyle";
                    }
                    prepared_types[type] = true;
                }
            }
            results = prepared;
        };

        try {
        auto result = ai::think(
            request.self,
            request.enemy,
            search::Result(),
            this->configs,
            request.target_point,
            ai::style::Data(),
            request.trigger,
            request.stretch,
            prepare
        );

        return Reply {
            .placement = result.placement,
            .eval = result.eval,
            .trigger = result.update.trigger
        };
        }
        catch (const BuildRequired&) {
            // The caller must release DOWN before asking for this previously unnecessary beam.
            return Reply { .placement = move::Placement(), .build_required = true };
        }
    };

    // One-player thinking (challenge modes): there is no opponent to read, so none of the versus logic runs.
    // It builds the way the 1P benchmark does (beam search over the visible pairs plus sampled futures,
    // best expected chain first) and reports the best chain that can be fired right now within the three
    // visible pairs. The caller decides when to fire: `fire` returns that chain's placement instead.
    Reply think_solo(Request& request, bool fire, i32& attack_score, i32& attack_chain,
                     std::optional<Reply>* fire_choice = nullptr)
    {
        attack_score = 0;
        attack_chain = 0;

        // The attack search takes the whole tree of its queue: only the pairs the game shows
        cell::Queue shown(request.self.queue.begin(), request.self.queue.begin() + std::min(request.self.queue.size(), request.attack_pairs));
        auto attacks = dfs::attack::search(request.self.field, shown);

        bool has_attack = false;
        dfs::attack::Data best_attack;
        move::Placement best_attack_placement;

        for (auto& candidate : attacks.candidates) {
            if (candidate.attacks.empty()) {
                continue;
            }

            if (!has_attack || dfs::attack::cmp_main(best_attack, candidate.attack_max)) {
                has_attack = true;
                best_attack = candidate.attack_max;
                best_attack_placement = candidate.placement;
            }
        }

        if (has_attack) {
            attack_score = best_attack.score;
            attack_chain = best_attack.count;
        }

        std::optional<Reply> firing;
        if (has_attack) {
            firing = Reply { .placement = best_attack_placement, .eval = best_attack.score, .trigger = {} };
            std::stable_sort(attacks.candidates.begin(), attacks.candidates.end(), [](const auto& a, const auto& b) {
                return dfs::attack::cmp_main(b.attack_max, a.attack_max);
            });
            for (auto& candidate : attacks.candidates) firing->alternatives.push_back(candidate.placement);
            if (fire_choice) *fire_choice = firing;
        }
        if (fire && firing) {
            return *firing;
        }

        beam::Configs beam_configs;
        beam_configs.width = request.beam_width;
        beam_configs.depth = request.beam_depth;

        auto build = beam::search_multi(
            request.self.field,
            request.self.queue,
            this->configs.build,
            beam_configs
        );

        if (build.candidates.empty()) {
            if (has_attack) {
                return Reply { .placement = best_attack_placement, .eval = best_attack.score, .trigger = {} };
            }

            return Reply {};
        }

        Reply reply { .placement = build.candidates.front().placement, .eval = i32(build.candidates.front().score), .trigger = {} };
        for (auto& candidate : build.candidates) reply.alternatives.push_back(candidate.placement);
        return reply;
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
};

GameResult play(Engine* engines[2], u32 seed, i32 first, const Options& options, std::ofstream& log)
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
        if (log.is_open()) {
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

        if (log.is_open() && chain.count > 0) {
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

        if (self.field.is_dead(rule::TSU)) {
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

                if (self.field.is_dead(rule::TSU)) {
                    return finish(o, "garbage", self.free_at);
                }
            }
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

    std::ofstream log;

    if (!options.log.empty()) {
        log.open(options.log);
    }

    printf("A: %s\nB: %s\n", engine_a->name().c_str(), engine_b->name().c_str());
    printf("games: %d, first seed: %u, target point: %d\n\n", options.games, options.seed, options.target_point);
    printf("game\tseed\twinner\treason\tticks\tmoves_A\tmoves_B\tchain_A\tchain_B\tsent_A\tsent_B\n");

    for (i32 g = 0; g < options.games; ++g) {
        u32 seed = options.seed + u32(g);
        i32 first = g % 2;

        auto t0 = std::chrono::steady_clock::now();
        auto result = play(engines, seed, first, options, log);
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
        else if (args[i] == "--log") {
            options.log = next();
        }
        else {
            specs.push_back(args[i]);
        }
    }

    if (specs.size() != 2) {
        fprintf(stderr,
            "usage: pvp [--games N] [--seed S] [--target P] [--max-moves M] [--verbose] [--log moves.jsonl] <engine A> <engine B>\n"
            "       pvp --engine [config.json]\n"
            "an engine is `local`, `local:<config.json>` or a command line that speaks the engine protocol\n");
        return 1;
    }

    return match(specs[0], specs[1], options);
};

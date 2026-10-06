#pragma once

// Engines that answer a request with a placement: this program's own AI in process, or any command
// line that runs the JSON line protocol. Included by pvp/main.cpp inside namespace pvp.

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
                && old.beam_width == request.beam_width && old.beam_depth == request.beam_depth
                && old.beam_target == request.beam_target && old.beam_zoro == request.beam_zoro;
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
                                  request.stretch, request.beam_width, request.beam_depth,
                                  request.beam_target, request.beam_zoro);
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
        beam_configs.target = request.beam_target;
        beam_configs.zoro = request.beam_zoro;

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
        // Keep transient inheritable pipe ends private while another worker
        // starts its engine. Otherwise parallel children can retain each
        // other's pipes and prevent EOF on shutdown.
        static std::mutex spawning;
        std::lock_guard<std::mutex> spawn_lock(spawning);
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
        si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
        si.wShowWindow = SW_HIDE;
        si.hStdInput = child_in_r;
        si.hStdOutput = child_out_w;
        si.hStdError = GetStdHandle(STD_ERROR_HANDLE);

        std::string cmd = this->command;

        if (!CreateProcessA(NULL, cmd.data(), NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, NULL, &si, &this->process)) {
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

        for (int fd : {in[0], in[1], out[0], out[1]}) fcntl(fd, F_SETFD, FD_CLOEXEC);

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

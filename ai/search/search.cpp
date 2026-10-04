#include "search.h"

namespace search
{

Thread::Thread()
{
    this->thread = nullptr;
    this->results = {};
};

// Starts the search thread
// We search all the configuration weights provided
bool Thread::search(Field field, cell::Queue queue, Configs configs, std::optional<i32> trigger, bool stretch, size_t beam_width, size_t beam_depth, size_t beam_target, bool beam_zoro)
{
    if (this->thread != nullptr) {
        return false;
    }

    this->clear();

    this->thread = new std::thread([&] (Field f, cell::Queue q, Configs w, std::optional<i32> t, bool s, size_t bw, size_t bd, size_t bt, bool bz) {
        auto r = Result();

        if (q.size() < 2) {
            this->results = r;
            return;
        }

        auto beam_configs = beam::Configs();
        beam_configs.width = bw;
        beam_configs.depth = bd;
        beam_configs.target = bt;
        beam_configs.zoro = bz;

        if (t.has_value()) {
            beam_configs.trigger = t.value();
            beam_configs.stretch = s;
        }

        // The beam search takes every visible pair and samples the rest of the queue up to its depth
        // Only a queue that already covers the whole depth (e.g. a known queue) is searched as it is
        if (q.size() >= beam_configs.depth) {
            r.build = beam::search(f, q, w.build, beam_configs);

            if (!r.build.candidates.empty()) {
                std::sort(
                    r.build.candidates.begin(),
                    r.build.candidates.end(),
                    [&] (const beam::Candidate& a, const beam::Candidate& b) {
                        return beam::compare(a, b, beam_configs);
                    }
                );
            }
        }
        else {
            r.build = beam::search_multi(f, q, w.build, beam_configs);
        }

        // The dfs builds search the full tree of the queue, so they only take the first 2 pairs
        cell::Queue q2 = { q[0], q[1] };

        r.freestyle = dfs::build::search(f, q2, w.freestyle);
        r.fast = dfs::build::search(f, q2, w.fast);
        r.ac = dfs::build::search(f, q2, w.ac);

        this->results = r;
    }, field, queue, configs, trigger, stretch, beam_width, beam_depth, beam_target, beam_zoro);

    return true;
};

std::optional<Result> Thread::get()
{
    if (this->thread == nullptr) {
        return {};
    }

    if (this->thread->joinable()) {
        this->thread->join();
    };

    auto result = this->results;

    this->clear();

    return result;
};

void Thread::clear()
{
    if (this->thread != nullptr) {
        if (this->thread->joinable()) {
            this->thread->join();
        }

        delete this->thread;
    }

    this->thread = nullptr;
    this->results = {};
};

};
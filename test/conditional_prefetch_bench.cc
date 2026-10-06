#include "../ai/search/beam/beam.h"
#include <atomic>
#include <chrono>
#include <fstream>
#include <iostream>
#include <numeric>
#include <stdexcept>

// Standalone experiment only: ordinary production engine and protocol are unchanged.
// A shared B,C prefix is narrowed before D; each of 16 ordered D pairs then has
// one deterministic continuation and its own bounded beam.
namespace conditional_bench {
using Clock = std::chrono::steady_clock;

static Field parse_field(const json& js) {
    auto rows = js.get<std::vector<std::string>>();
    if (rows.size() != 14) throw std::runtime_error("field must have 14 rows");
    for (const auto& row : rows) if (row.size() != 6) throw std::runtime_error("field rows must have 6 cells");
    char cells[13][7] = {};
    for (int y = 0; y < 13; ++y)
        for (int x = 0; x < 6; ++x) cells[y][x] = rows[y + 1][x];
    Field field;
    field.from(cells);
    for (int x = 0; x < 6; ++x) if (rows[0][x] == '#') field.row14 |= 1 << x;
    return field;
}

static json field_rows(Field field) {
    json rows = json::array();
    std::string upper;
    for (int x = 0; x < 6; ++x) upper += ((field.row14 >> x) & 1) ? '#' : '.';
    rows.push_back(upper);
    for (int y = 12; y >= 0; --y) {
        std::string row;
        for (int x = 0; x < 6; ++x) row += cell::to_char(field.get_cell(x, y));
        rows.push_back(row);
    }
    return rows;
}

static cell::Queue parse_queue(const json& js) {
    cell::Queue queue;
    for (const auto& entry : js) {
        auto pair = entry.get<std::string>();
        if (pair.size() != 2) throw std::runtime_error("queue pairs must have 2 characters");
        auto a = cell::from_char(pair[0]), b = cell::from_char(pair[1]);
        if (int(a) >= 4 || int(b) >= 4) throw std::runtime_error("queue pairs must use R,Y,G,B");
        queue.push_back({a, b});
    }
    if (queue.size() < 3) throw std::runtime_error("queue must contain B,C,actual D");
    return {queue[0], queue[1], queue[2]};
}

static json placement_json(move::Placement p) {
    return {{"x", int(p.x)}, {"r", std::string(1, "URDL"[int(p.r)])}};
}

static int baseline_rank(move::Placement p, const beam::Result& baseline) {
    for (size_t i = 0; i < baseline.candidates.size(); ++i)
        if (p == baseline.candidates[i].placement) return int(i);
    return 1000 + int(p.x) * 4 + int(p.r);
}

static void choose_order(beam::Result& result, const beam::Result& baseline, const beam::Configs& cfg) {
    // Keep the ordinary baseline's order for tied values. Scores in this result
    // represent one continuation; unlike search_multi they are not sums of six.
    std::stable_sort(result.candidates.begin(), result.candidates.end(), [&](const auto& a, const auto& b) {
        if (a.score != b.score) {
            bool both_enough = a.score >= cfg.trigger && b.score >= cfg.trigger;
            if (!cfg.stretch && both_enough) return a.score < b.score;
            return a.score > b.score;
        }
        return baseline_rank(a.placement, baseline) < baseline_rank(b.placement, baseline);
    });
}

static json result_json(const beam::Result& result, Field field, cell::Pair current,
                        size_t score_samples, bool fallback_used = false) {
    json output = {{"candidates", json::array()}, {"fallback_used", fallback_used}, {"score_samples", score_samples}};
    for (const auto& candidate : result.candidates) {
        auto c = placement_json(candidate.placement);
        c["score"] = candidate.score;
        c["mean_score"] = double(candidate.score) / score_samples;
        output["candidates"].push_back(c);
    }
    if (!result.candidates.empty()) {
        auto chosen = result.candidates.front().placement;
        int top_tie_count = 0;
        for (const auto& candidate : result.candidates)
            if (candidate.score == result.candidates.front().score) ++top_tie_count;
        output["top_score_tie_count"] = top_tie_count;
        output["tie_break_used"] = top_tie_count > 1;
        output["selected"] = placement_json(chosen);
        field.drop_pair(chosen.x, chosen.r, current);
        auto popped = field.pop();
        auto score = chain::get_score(popped);
        output["next_field"] = field_rows(field);
        output["next_score"] = score.score;
        output["next_chain"] = score.count;
    } else {
        output["top_score_tie_count"] = 0;
        output["tie_break_used"] = false;
        output["selected"] = nullptr;
        output["next_field"] = nullptr;
    }
    return output;
}

struct Prefix {
    beam::Result result;
    beam::Result tie_order;
    std::vector<beam::node::Data> nodes;
    std::vector<beam::node::Data> raw_nodes;
    size_t width = 0;
    bool enough = false;
};

static Prefix shared_prefix(Field field, const cell::Queue& queue,
                            const beam::eval::Weight& weights, const beam::Configs& cfg) {
    Prefix prefix;
    prefix.width = cfg.width;
    beam::node::Data root{.field = field, .score = {0,0}, .index = -1};
    beam::Layer roots(cfg.width), children(cfg.width);
    std::vector<int> static_scores;
    beam::expand(queue[0], root, weights, [&](auto& child, const auto& placement, const auto& score) {
        child.index = int(prefix.result.candidates.size());
        prefix.result.candidates.push_back({placement, size_t(score.score)});
        beam::eval::evaluate(child, weights);
        static_scores.push_back(child.score.eval + child.score.action);
        roots.data.push_back(child);
    });
    if (prefix.result.candidates.empty()) return prefix;
    beam::think(queue[1], prefix.result.candidates, roots, children, weights);
    prefix.raw_nodes = children.data;
    children.sort();
    prefix.nodes = children.data;
    for (const auto& node : prefix.nodes)
        static_scores[node.index] = std::max(static_scores[node.index], node.score.eval + node.score.action);
    prefix.tie_order = prefix.result;
    auto candidate_index = [&](move::Placement placement) {
        for (size_t i = 0; i < prefix.result.candidates.size(); ++i)
            if (placement == prefix.result.candidates[i].placement) return i;
        return size_t(0);
    };
    std::stable_sort(prefix.tie_order.candidates.begin(), prefix.tie_order.candidates.end(), [&](const auto& a, const auto& b) {
        return static_scores[candidate_index(a.placement)] > static_scores[candidate_index(b.placement)];
    });
    for (const auto& c : prefix.result.candidates)
        if (c.score >= cfg.trigger) prefix.enough = true;
    return prefix;
}

static beam::Result one_branch(const Prefix& prefix, cell::Pair pair,
                              const cell::Queue& future, const beam::eval::Weight& weights,
                              beam::Configs cfg) {
    auto result = prefix.result;
    if (prefix.enough || prefix.nodes.empty()) return result;
    std::array<beam::Layer, 2> layers = {beam::Layer(cfg.width), beam::Layer(cfg.width)};
    // Ordinary search cleared its original root layer after C, including age.
    layers[1].table.update();
    // Prefix nodes are already in descending static/action order. Narrow before
    // enumerating D so its first expansion also fits the branch's small budget.
    if (cfg.width == prefix.width) {
        // Preserve ordinary heap ordering exactly for the wide-prefix check.
        layers[0].data = prefix.raw_nodes;
    } else {
        for (size_t i = 0; i < std::min(cfg.width, prefix.nodes.size()); ++i)
            layers[0].data.push_back(prefix.nodes[i]);
        // Layer::sort expects a heap whenever size == width.
        if (layers[0].data.size() == cfg.width)
            std::make_heap(layers[0].data.begin(), layers[0].data.end(),
                          [](const auto& a, const auto& b) { return b < a; });
    }
    cell::Queue suffix = {pair};
    suffix.insert(suffix.end(), future.begin(), future.end());
    for (size_t i = 0; i < suffix.size(); ++i) {
        beam::think(suffix[i], result.candidates, layers[i & 1], layers[(i + 1) & 1], weights);
        bool enough = false;
        for (const auto& c : result.candidates) if (c.score >= cfg.trigger) enough = true;
        if (enough) break;
    }
    return result;
}

static bool same_scores(const beam::Result& a, const beam::Result& b) {
    if (a.candidates.size() != b.candidates.size()) return false;
    for (const auto& x : a.candidates) {
        bool found = false;
        for (const auto& y : b.candidates)
            if (x.placement == y.placement) { found = x.score == y.score; break; }
        if (!found) return false;
    }
    return true;
}

static json run(const json& input, const beam::eval::Weight& weights) {
    const auto& self = input.contains("self") ? input.at("self") : input;
    auto field = parse_field(self.at("field"));
    auto queue = parse_queue(self.at("queue"));
    beam::Configs cfg;
    cfg.width = input.value("prefix_width", size_t(50));
    cfg.depth = input.value("depth", size_t(8));
    cfg.trigger = input.value("trigger", size_t(130000));
    cfg.stretch = input.value("stretch", true);
    if (cfg.depth < 3 || cfg.width < 1) throw std::runtime_error("depth >= 3 and prefix_width >= 1 required");
    auto widths = input.value("widths", std::vector<size_t>{8,12,18,25});
    auto repeats = std::clamp(input.value("repetitions", 1), 1, 20);
    auto threads = std::clamp(input.value("threads", 6), 1, 16);
    auto future_id = std::clamp(input.value("future_id", 0), 0, int(beam::BRANCH) - 1);
    auto use_baseline_ties = input.value("use_baseline_ties", true);
    // Preserve get_queue_random's current odd-count rounding, just like ordinary
    // search_multi. With three known pairs, depth 8 currently searches 9 pairs.
    auto future = beam::get_queue_random(future_id, cfg.depth - 3);
    json output = {{"depth", cfg.depth}, {"effective_branch_depth", 3 + future.size()},
                   {"prefix_width", cfg.width}, {"future_id", future_id},
                   {"threads", threads}, {"trigger",cfg.trigger}, {"stretch",cfg.stretch},
                   {"tie_policy",use_baseline_ties ? "ordinary_bc" : "shared_prefix_static"},
                   {"scope","beam construction only; no attack DFS or live input"},
                   {"variants", json::array()}};
    if (input.contains("id")) output["id"] = input["id"];
    auto baseline = [&](cell::Queue known, const char* key) {
        std::vector<double> times;
        beam::Result result;
        for (int i = 0; i < repeats; ++i) {
            auto started = Clock::now();
            result = beam::search_multi(field, known, weights, cfg);
            times.push_back(std::chrono::duration<double,std::milli>(Clock::now() - started).count());
        }
        auto js = result_json(result, field, queue[0], beam::BRANCH);
        js["timings_ms"] = times;
        js["ms"] = std::accumulate(times.begin(), times.end(), 0.0) / times.size();
        output[key] = js;
        return result;
    };
    auto baseline_bc = baseline({queue[0],queue[1]}, "baseline_bc");
    baseline(queue, "baseline_bcd");

    for (auto width : widths) {
        if (!width) throw std::runtime_error("branch width must be >= 1");
        std::vector<double> times, prefix_times;
        std::vector<beam::Result> results(16);
        for (int repetition = 0; repetition < repeats; ++repetition) {
            auto started = Clock::now();
            auto prefix = shared_prefix(field, queue, weights, cfg);
            prefix_times.push_back(std::chrono::duration<double,std::milli>(Clock::now() - started).count());
            auto narrow_cfg = cfg;
            narrow_cfg.width = width;
            std::atomic<int> next{0};
            std::vector<std::thread> workers;
            for (int i = 0; i < threads; ++i) workers.emplace_back([&] {
                while (true) {
                    int id = next.fetch_add(1);
                    if (id >= 16) break;
                    auto pair = cell::Pair{cell::Type(id/4),cell::Type(id%4)};
                    results[id] = one_branch(prefix, pair, future, weights, narrow_cfg);
                    choose_order(results[id], use_baseline_ties ? baseline_bc : prefix.tie_order, narrow_cfg);
                }
            });
            for (auto& worker : workers) worker.join();
            times.push_back(std::chrono::duration<double,std::milli>(Clock::now() - started).count());
        }
        json variant = {{"width",width}, {"timings_ms",times}, {"prefix_timings_ms",prefix_times},
                        {"ms",std::accumulate(times.begin(),times.end(),0.0)/times.size()}, {"branches",json::array()}};
        variant["marginal_ms"] = variant["ms"];
        variant["total_required_ms"] = (use_baseline_ties ? output["baseline_bc"]["ms"].get<double>() : 0.0)
            + variant["ms"].get<double>();
        variant["tie_policy"] = output["tie_policy"];
        for (int id = 0; id < 16; ++id) {
            bool fallback = true;
            for (const auto& c : results[id].candidates) if (c.score != 0) fallback = false;
            auto report = result_json(results[id], field, queue[0], 1, fallback);
            report["pair"] = std::string() + cell::to_char(cell::Type(id/4)) + cell::to_char(cell::Type(id%4));
            variant["branches"].push_back(report);
        }
        output["variants"].push_back(variant);
    }
    if (input.value("verify_prefix", false)) {
        auto check_cfg = cfg;
        check_cfg.depth = 3;
        auto prefix = shared_prefix(field, queue, weights, check_cfg);
        int passed = 0;
        for (int id = 0; id < 16; ++id) {
            auto pair = cell::Pair{cell::Type(id/4),cell::Type(id%4)};
            auto shared = one_branch(prefix,pair,{},weights,check_cfg);
            auto independent = beam::search(field,{queue[0],queue[1],pair},weights,check_cfg);
            if (same_scores(shared,independent)) ++passed;
        }
        output["prefix_exact_check"] = {{"passed",passed},{"total",16},{"width",cfg.width},{"depth",3}};
    }
    return output;
}
} // namespace conditional_bench

int main(int argc, char** argv) {
    try {
        std::ifstream config(argc > 1 ? argv[1] : "config.json");
        if (!config) throw std::runtime_error("cannot read config");
        json config_json;
        config >> config_json;
        auto weights = config_json.at("build").get<beam::eval::Weight>();
        std::string line;
        while (std::getline(std::cin,line)) {
            if (line.empty()) continue;
            try {
                std::cout << conditional_bench::run(json::parse(line),weights).dump() << std::endl;
            } catch (const std::exception& e) {
                std::cout << json{{"error",e.what()}}.dump() << std::endl;
            }
        }
    } catch (const std::exception& e) {
        std::cerr << e.what() << std::endl;
        return 1;
    }
    return 0;
}

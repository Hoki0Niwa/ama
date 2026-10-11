#pragma once
#include "../evaluation.h"
#include "../text.h"
#include <chrono>
#include <map>
#include <unordered_map>

// Research-only observers. They never write a node, layer, table or score.
namespace fever::research {
using json = nlohmann::json;
struct Witness {
    int links=0, excess=0, remaining=0, key=0, column=-1, color=-1, headroom=0;
    int popped=0;
    i32 value=0;
};
struct Record {
    beam::node::Data node;
    Witness witness;
    int state=0; // 0 kept, 1 width rejected, 2 width evicted, 3 TT, 4 chain prune
    int actual_chain=0;
};
struct LayerTrace {
    int depth=0;
    std::map<int,std::map<std::string,u64>> counts;
    std::vector<Record> records;
    std::map<std::string,std::vector<size_t>> active;
    std::vector<beam::node::Data> exemplars;
    size_t parents=0, survivors=0;
    bool conservation=true;
    std::chrono::steady_clock::time_point start;
    double cpu_start=0, wall_ms=0, thread_cpu_seconds=0;
};
struct ThreadTrace {
    int virtual_id=0, completed_depth=0;
    std::vector<LayerTrace> layers;
    std::vector<json> roots;
    json final_candidates=json::array();
    std::unordered_map<u64,Witness> witnesses;
    Witness last;
    u64 expansions=0, attempts=0, evaluations=0, potential_calls=0, potential_pops=0;
    u64 extra_potential_calls=0;
    double wall_ms=0;
    size_t memory_lower_bound_bytes=0;
};
extern thread_local ThreadTrace* current;
extern bool enabled;
extern int placed_total;
extern bool detail_all;
extern json request_traces;
extern thread_local bool extra_potential;
void begin_request(bool on, int t, bool all);
json finish_request();
void potential_begin(Field field, const Configs& cfg);
void witness(Field remain, avec<Field,19>& masks, int x, int color, int key, int links, i32 value);
void potential_pop();
void evaluate_begin(int root);
void evaluate_end(const beam::node::Data& node);
void begin_layer(int depth, size_t parents);
void parent(int root, size_t locks);
void rejected(int root, const char* reason);
void legal(int root);
void dropped(const beam::node::Data& child, const beam::eval::Weight& w, const Configs& cfg, int state, int actual_chain);
void before_add(const beam::node::Data& child, const beam::Layer& layer, const beam::eval::Weight& w, const Configs& cfg, int actual_chain);
void root_node(const beam::node::Data& child, const move::Placement& move, int actual_chain);
void finish_layer(const beam::Layer& children);
void completed(const Result& result);
json serialize(const ThreadTrace& trace);
struct MultiTrace {
    bool on=false;
    std::vector<ThreadTrace> threads;
    std::chrono::steady_clock::time_point start;
    double cpu_start=0;
    json meta;
    MultiTrace(Field field,const Queue& queue,const dropset::Character& character,u64 index,const Configs& cfg);
    ~MultiTrace();
};
struct ThreadScope {
    ThreadTrace* previous=nullptr;
    std::chrono::steady_clock::time_point start;
    ThreadScope(MultiTrace& multi,size_t id);
    ~ThreadScope();
};
}

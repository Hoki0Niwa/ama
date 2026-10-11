#include "first40_diagnostics.h"
#include <ctime>
#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <psapi.h>
#endif

namespace fever::research {
thread_local ThreadTrace* current=nullptr;
thread_local bool extra_potential=false;
bool enabled=false, detail_all=false;
int placed_total=0;
json request_traces=json::array();
static int colored(Field field) {
    int n=0; for(int c=0;c<cell::COUNT-1;++c)n+=field.data[c].get_count(); return n;
}
static auto rows(Field field) { return text::from_field(field); }
static double cpu_seconds() {
#if defined(_WIN32)
    FILETIME a,b,k,u;
    if(GetProcessTimes(GetCurrentProcess(),&a,&b,&k,&u))
        return double((u64(k.dwHighDateTime)<<32)+k.dwLowDateTime+(u64(u.dwHighDateTime)<<32)+u.dwLowDateTime)/1e7;
#endif
    return double(std::clock())/CLOCKS_PER_SEC;
}
static double thread_cpu_seconds() {
#if defined(_WIN32)
    FILETIME a,b,k,u;
    if(GetThreadTimes(GetCurrentThread(),&a,&b,&k,&u))
        return double((u64(k.dwHighDateTime)<<32)+k.dwLowDateTime+(u64(u.dwHighDateTime)<<32)+u.dwLowDateTime)/1e7;
    return 0;
#else
    // A portable thread clock is not provided by this Windows research build.
    return 0;
#endif
}
static json memory() {
#if defined(_WIN32)
    PROCESS_MEMORY_COUNTERS m{};m.cb=sizeof(m);
    if(GetProcessMemoryInfo(GetCurrentProcess(),&m,sizeof(m)))
        return {{"working_set_bytes",m.WorkingSetSize},{"lifetime_peak_working_set_bytes",m.PeakWorkingSetSize}};
#endif
    return nullptr;
}
void begin_request(bool on,int t,bool all) {
    enabled=on;placed_total=t;detail_all=all;request_traces=json::array();
}
json finish_request() {
    enabled=false;
    return {{"schema","ama.f40.diagnostics.v1"},{"searches",std::move(request_traces)},
        {"memory_after_search",memory()},
        {"record_columns",{"root","board_hash","action","eval","state","Lg","Eg","Rg","Kg","Xg","color","Hg","popped","witness_value","actual_chain"}},
        {"state_codes",{{"0","kept"},{"1","width_rejected"},{"2","width_evicted"},{"3","TT_action_cut"},{"4","actual_chain_prune"}}},
        {"warning","Geometric keys and virtual colors are not legal completion witnesses."}};
}
void potential_begin(Field field,const Configs& cfg) {
    if(!current)return;
    if(extra_potential)++current->extra_potential_calls;else ++current->potential_calls;
    u8 h[6];field.get_heights(h);
    current->last={};current->last.column=-1;current->last.color=-1;
    current->last.remaining=colored(field);
    current->last.headroom=std::min(11-int(cfg.rules.margin)-int(h[2]),11-int(cfg.rules.margin)-int(h[3]));
}
void potential_pop() { if(current)++current->potential_pops; }
void witness(Field remain,avec<Field,19>& masks,int x,int color,int key,int links,i32 value) {
    if(!current)return;
    int popped=0;for(int i=0;i<masks.get_size();++i)popped+=colored(masks[i]);
    auto& g=current->last;g.links=links;g.excess=popped-4*links;g.remaining=colored(remain);
    g.key=key;g.column=x;g.color=color;g.popped=popped;g.value=value;
}
void evaluate_begin(int root) {
    if(current) {++current->evaluations;++current->layers.back().counts[root]["b0_evaluations"];}
}
void evaluate_end(const beam::node::Data& node) {
    if(current)current->witnesses[beam::node::get_hash(node)]=current->last;
}
void begin_layer(int depth,size_t parents) {
    if(!current)return;
    current->layers.emplace_back();auto& layer=current->layers.back();layer.depth=depth;layer.parents=parents;
    layer.start=std::chrono::steady_clock::now();layer.cpu_start=thread_cpu_seconds();
}
void parent(int root,size_t locks) {
    if(!current)return;
    ++current->expansions;current->attempts+=locks;
    auto& c=current->layers.back().counts[root];++c["parents"];c["placement_attempts"]+=locks;
}
void rejected(int root,const char* reason) {
    if(current)++current->layers.back().counts[root][reason];
}
void legal(int root) { rejected(root,"legal_children"); }
static Witness get_witness(const beam::node::Data& node,const beam::eval::Weight& w,const Configs& cfg) {
    auto hash=beam::node::get_hash(node);auto it=current->witnesses.find(hash);
    if(it!=current->witnesses.end())return it->second;
    // TT stores only a short hash and clamped eval. Recompute geometry for the
    // actual board on a diagnostic copy; this never supplies the B0 eval.
    extra_potential=true;potential(node.field,w,cfg);extra_potential=false;
    current->witnesses[hash]=current->last;return current->last;
}
static std::string identity(const beam::node::Data& node) {
    // Full board, root and exact score distinguish cross-root TT / duplicates.
    auto board=rows(node.field);std::string s;
    for(auto& r:board)s+=r;
    return s+":"+std::to_string(node.index)+":"+std::to_string(node.score.action)+":"+std::to_string(node.score.eval);
}
void dropped(const beam::node::Data& child,const beam::eval::Weight& w,const Configs& cfg,int state,int actual_chain) {
    if(!current)return;
    auto& layer=current->layers.back();
    layer.records.push_back({child,get_witness(child,w,cfg),state,actual_chain});
    ++layer.counts[child.index][state==3?"tt_cut":"chain_prune"];
}
void before_add(const beam::node::Data& child,const beam::Layer& children,const beam::eval::Weight& w,const Configs& cfg,int actual_chain) {
    if(!current)return;
    auto& layer=current->layers.back();int state=0;
    if(children.data.size()>=children.width) {
        if(!(children.data.front()<child)) {state=1;++layer.counts[child.index]["width_rejected"];}
        else {
            const auto& weakest=children.data.front();auto key=identity(weakest);
            auto& ids=layer.active[key];if(ids.empty())throw std::runtime_error("diagnostic heap identity missing");
            auto id=ids.back();ids.pop_back();layer.records[id].state=2;
            ++layer.counts[weakest.index]["width_evicted"];
        }
    }
    const size_t id=layer.records.size();layer.records.push_back({child,get_witness(child,w,cfg),state,actual_chain});
    ++layer.counts[child.index]["eligible"];
    if(state==0)layer.active[identity(child)].push_back(id);
}
void root_node(const beam::node::Data& child,const move::Placement& move,int actual_chain) {
    if(!current)return;
    auto& layer=current->layers.back();layer.records.push_back({child,current->last,0,actual_chain});
    layer.active[identity(child)].push_back(layer.records.size()-1);
    ++layer.counts[child.index]["eligible"];
    current->roots.push_back({{"root",child.index},{"x",move.x},{"r",std::string(1,text::from_direction(move.r))}});
}
void finish_layer(const beam::Layer& children) {
    if(!current)return;
    auto& layer=current->layers.back();layer.survivors=children.data.size();
    std::map<std::string,size_t> actual;
    for(const auto& node:children.data) {++actual[identity(node)];++layer.counts[node.index]["kept"];}
    for(const auto& [key,ids]:layer.active)if(actual[key]!=ids.size())layer.conservation=false;
    size_t n=0;for(const auto& [key,ids]:layer.active)n+=ids.size();
    if(n!=children.data.size())layer.conservation=false;
    current->memory_lower_bound_bytes+=layer.records.capacity()*sizeof(Record);
    layer.wall_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-layer.start).count();
    layer.thread_cpu_seconds=thread_cpu_seconds()-layer.cpu_start;
}
void completed(const Result& result) {
    if(!current)return;
    current->completed_depth=result.completed_depth;
    int id=0;for(const auto& c:result.candidates)current->final_candidates.push_back({{"root",id++},
        {"x",c.placement.x},{"r",std::string(1,text::from_direction(c.placement.r))},
        {"chain",c.chain},{"score",c.score},{"aim",c.aim},{"next_room",c.next_room}});
}
static json features(const Witness& g) {
    return {{"Lg",g.links},{"Eg",g.excess},{"Rg",g.remaining},{"Kg",g.key},{"Xg",g.column},
        {"color",g.color},{"Hg",g.headroom},{"popped",g.popped},{"value",g.value}};
}
json serialize(const ThreadTrace& trace) {
    json layers=json::array();
    for(const auto& layer:trace.layers) {
        json roots=json::array(),records=json::array(),examples=json::array();
        std::map<std::pair<int,int>,const Record*> best;
        for(const auto& record:layer.records) {
            const auto& n=record.node;const auto& g=record.witness;
            if(detail_all)records.push_back(json::array({json(n.index),json(beam::node::get_hash(n)),json(n.score.action),json(n.score.eval),
                json(record.state),json(g.links),json(g.excess),json(g.remaining),json(g.key),json(g.column),json(g.color),json(g.headroom),
                json(g.popped),json(g.value),json(record.actual_chain)}));
            auto key=std::make_pair(n.index,record.state);auto it=best.find(key);
            if(it==best.end() || std::make_tuple(g.links,-g.excess,-g.remaining,g.headroom)>
                std::make_tuple(it->second->witness.links,-it->second->witness.excess,-it->second->witness.remaining,it->second->witness.headroom))best[key]=&record;
        }
        for(const auto& [root,counts]:layer.counts)roots.push_back({{"root",root},{"counts",counts}});
        for(const auto& [key,r]:best)examples.push_back({{"root",key.first},{"state",key.second},
            {"board",rows(r->node.field)},{"hash",beam::node::get_hash(r->node)},
            {"action",r->node.score.action},{"eval",r->node.score.eval},{"geometry",features(r->witness)}});
        layers.push_back({{"depth",layer.depth},{"parents",layer.parents},{"survivors",layer.survivors},
            {"wall_ms",layer.wall_ms},{"thread_cpu_seconds",layer.thread_cpu_seconds},
            {"record_storage_bytes",layer.records.capacity()*sizeof(Record)},
            {"conservation",layer.conservation},{"roots",roots},{"records",std::move(records)},
            {"examples",std::move(examples)}});
    }
    return {{"virtual_id",trace.virtual_id},{"completed_depth",trace.completed_depth},
        {"expansion_nodes",trace.expansions},{"placement_attempts",trace.attempts},
        {"b0_evaluations",trace.evaluations},{"b0_potential_calls",trace.potential_calls},
        {"diagnostic_extra_potential_calls",trace.extra_potential_calls},{"potential_pops",trace.potential_pops},
        {"thread_wall_ms",trace.wall_ms},{"diagnostic_storage_lower_bound_bytes",trace.memory_lower_bound_bytes},
        {"root_placements",trace.roots},{"final_candidates",trace.final_candidates},{"layers",std::move(layers)}};
}
MultiTrace::MultiTrace(Field field,const Queue& queue,const dropset::Character& character,u64 index,const Configs& cfg) {
    on=enabled;if(!on)return;
    threads.resize(VIRTUAL_COUNT);start=std::chrono::steady_clock::now();cpu_start=cpu_seconds();
    json visible=json::array();for(auto& piece:queue)visible.push_back(text::from_piece(piece));
    meta={{"field",text::from_field(field)},{"visible",visible},{"character",character.id},
        {"dropset_index",index},{"placed_total",placed_total},{"remaining",40-placed_total},
        {"width",cfg.width},{"depth_limit",cfg.depth},{"margin",cfg.rules.margin},
        {"trigger",cfg.trigger},{"build_chain",cfg.build_chain},{"record_detail",detail_all?"all":"summary"}};
}
MultiTrace::~MultiTrace() {
    if(!on)return;
    meta["beam_wall_ms"]=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
    meta["process_cpu_seconds"]=cpu_seconds()-cpu_start;
    meta["process_memory"]=memory();meta["virtual_searches"]=json::array();
    for(const auto& trace:threads)meta["virtual_searches"].push_back(serialize(trace));
    request_traces.push_back(std::move(meta));
}
ThreadScope::ThreadScope(MultiTrace& multi,size_t id) {
    previous=current;start=std::chrono::steady_clock::now();
    current=multi.on?&multi.threads[id]:nullptr;
    if(current)current->virtual_id=int(id);
}
ThreadScope::~ThreadScope() {
    if(current) {
        current->wall_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        current->memory_lower_bound_bytes+=current->witnesses.size()*(sizeof(u64)+sizeof(Witness));
    }
    current=previous;
}
}

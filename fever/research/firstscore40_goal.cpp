#include "firstscore40_goal.h"
#include <algorithm>
#include <functional>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace fever::research::firstscore40 {
namespace {
using Clock=std::chrono::steady_clock;
constexpr rule::Rule RULES=[] {auto value=rule::FEVER;value.plain_pairs=true;value.special_moves=true;return value;}();
struct Exhausted : std::runtime_error { using std::runtime_error::runtime_error; };
struct Work {
    Limits limits;
    Clock::time_point start=Clock::now(), end;
    int attempts=0, expansions=0, pops=0, evals=0, deaths=0, discarded=0;
    std::map<std::string,int> rejected;
    std::string stopped;
    Work(Limits l):limits(l),end(start+std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double,std::milli>(l.wall_ms))){}
    void check() { if(Clock::now()>=end) throw Exhausted("wall_budget"); }
    void transition() { check(); if(attempts>=limits.transitions)throw Exhausted("transition_limit"); ++attempts; }
    void witness() { check(); if(pops>=limits.witnesses)throw Exhausted("witness_limit"); ++pops; }
    json stats() { return {{"transition_attempts",attempts},{"expanded_parents",expansions},
        {"witness_pops",pops},{"witness_evaluations",evals},{"dead_children",deaths},
        {"discarded_children",discarded},{"rejected",rejected},{"stop_reason",stopped},
        {"wall_ms",std::chrono::duration<double,std::milli>(Clock::now()-start).count()}}; }
};
std::string path_key(const std::vector<move::Placement>& actions) {
    std::string key;for(auto a:actions){key+=char('0'+a.x);key+=text::from_direction(a.r);}return key;
}
std::vector<move::Placement> legal(Field field,const piece::Piece& value) {
    auto moves=normal_space::moves(field,value,RULES);
    std::vector<move::Placement> result;for(int i=0;i<moves.get_size();++i)result.push_back(moves[i]);
    std::sort(result.begin(),result.end(),[](auto a,auto b){return std::make_pair(a.x,text::from_direction(a.r))<std::make_pair(b.x,text::from_direction(b.r));});
    return result;
}
int room(Field field) { return std::min(10-int(field.get_height(2)),10-int(field.get_height(3))); }
json pose(move::Placement a) { return {{"x",a.x},{"r",std::string(1,text::from_direction(a.r))}}; }
std::optional<Witness> geometric(Field field,int x,int color,int max_key,const normal_scoring::Entry& scoring,Work& work) {
    work.check();++work.evals;int height=field.get_height(x);auto augmented=field;
    for(int k=1;k<=std::min(max_key,12-height);++k) {
        augmented.set_cell(x,height+k-1,cell::Type(color));
        if(augmented.data[color].get_mask_group_4(x,height).get_count()<4)continue;
        work.witness();auto remaining=augmented;auto masks=remaining.pop();
        auto copy=masks;auto score=normal_scoring::score(copy,scoring);
        Witness w;w.x=x;w.color=color;w.key=k;w.links=score.count;w.points=score.score;
        w.masks=masks;w.remaining=remaining;w.headroom=room(field);return w;
    }
    return std::nullopt;
}
Field augment(Field field,const Witness& witness) {
    int h=field.get_height(witness.x);
    for(int i=0;i<witness.key;++i)field.set_cell(witness.x,h+i,cell::Type(witness.color));
    return field;
}
struct Node { Field field;std::vector<move::Placement> path;bool build=true;int discard=0,min_room=99; };
struct Fire { Node node; int points=0,chain=0; };
json proof(const Observation& obs,const std::vector<move::Placement>& path) {
    json result=json::array();auto field=obs.field;auto scoring=normal_scoring::find(obs.character);
    for(size_t i=0;i<path.size();++i) {
        auto before=field;auto drop=field.drop_piece(path[i].x,path[i].r,obs.visible[i],RULES);
        if(!drop)throw std::runtime_error("proof illegal drop");
        auto masks=field.pop();auto copied=masks;auto score=normal_scoring::score(copied,*scoring);
        result.push_back({{"move",obs.t+int(i)+1},{"piece",text::from_piece(obs.visible[i])},
            {"placement",pose(path[i])},{"before",text::from_field(before)},{"after",text::from_field(field)},
            {"links",executed_links(masks)},{"score",score.score},{"discarded",drop->discarded},
            {"dead",field.is_dead(rule::FEVER)}});
    }
    return result;
}
json decision(const Observation& obs,const std::vector<move::Placement>& path,const char* source) {
    auto evidence=proof(obs,path);auto first=evidence[0];auto p=first["placement"];
    p["next_field"]=first["after"];p["next_chain"]=first["links"].size();p["next_score"]=first["score"];
    p["action_source"]=source;p["proof"]=std::move(evidence);return p;
}
std::string goal_id(const Observation& obs,const Witness& w,const std::vector<move::Placement>& path) {
    auto field=obs.field;std::string input=text::from_field(field)[0];
    for(auto& row:text::from_field(field))input+=row;
    input+=obs.character+":"+std::to_string(obs.t)+":"+std::to_string(obs.phase)+":"+std::to_string(w.x)+":"+std::to_string(w.color)+":"+path_key(path);
    for(auto p:obs.visible)input+=text::from_piece(p);
    uint64_t hash=14695981039346656037ULL;for(unsigned char c:input){hash^=c;hash*=1099511628211ULL;}
    std::ostringstream stream;stream<<std::hex<<hash;return stream.str();
}
json goal_json(const Goal& g,const char* status) {
    json actions=json::array(),after=json::array();for(auto a:g.actions)actions.push_back(pose(a));
    for(auto f:g.after)after.push_back(text::from_field(f));
    return {{"id",g.id},{"status",status},{"kind",g.kind},{"created_t",g.origin.t},
        {"phase",g.origin.phase},{"expires_t",g.origin.t+int(g.actions.size())},
        {"actions",actions},{"expected_fields_after_each_action",after},{"executed_steps",g.next},
        {"base_witness",witness_json(g.base)},{"planned_witness",witness_json(g.result)},
        {"evidence_level","G+P; actual first-mainline points belong to the referee"}};
}
}

json executed_links(avec<Field,19> masks) {
    json result=json::array();for(int i=0;i<masks.get_size();++i){json groups=json::array();int colors=0;
        for(int c=0;c<cell::COUNT-1;++c){auto bits=masks[i].data[c];if(bits.is_empty())continue;++colors;
            while(!bits.is_empty()){auto group=bits.get_mask_group_lsb();groups.push_back(group.get_count());bits=bits&~group;}}
        result.push_back({{"groups",groups},{"colors",colors}});
    }return result;
}

void trace_ids(Field origin,Field augmented,Witness& witness) {
    // y is bottom-up, identical to the shared bitboard. Negative IDs denote keys.
    struct Tagged { int id=-999;cell::Type color=cell::Type::NONE; };
    std::array<std::array<Tagged,13>,6> grid{};witness.stages.clear();
    int key_bottom=augmented.get_height(witness.x)-witness.key;
    for(int x=0;x<6;++x)for(int y=0;y<13;++y){auto color=augmented.get_cell(x,y);if(color==cell::Type::NONE)continue;
        int id=origin.get_cell(x,y)!=cell::Type::NONE?y*6+x:1000+y*6+x;
        if(x==witness.x&&y>=key_bottom)id=-(y-key_bottom+1);grid[x][y]={id,color};}
    for(int i=0;i<witness.masks.get_size();++i){auto mask=witness.masks[i].get_mask();
        // Shared masks omit adjacent nuisance; annotate its identical removal too.
        Field current;for(int x=0;x<6;++x)for(int y=0;y<13;++y)if(grid[x][y].color!=cell::Type::NONE)current.set_cell(x,y,grid[x][y].color);
        auto removal=mask|(mask.get_expand()&current.data[int(cell::Type::GARBAGE)]);
        for(int x=0;x<6;++x){std::array<Tagged,13> compact{};int n=0;
            for(int y=0;y<13;++y){auto tag=grid[x][y];if(tag.color==cell::Type::NONE)continue;
                if(removal.get_bit(x,y)){if(mask.get_bit(x,y))witness.stages[tag.id]=i+1;}
                else compact[n++]=tag;}grid[x]=compact;}
    }
    Field final;for(int x=0;x<6;++x)for(int y=0;y<13;++y)if(grid[x][y].color!=cell::Type::NONE)final.set_cell(x,y,grid[x][y].color);
    if(final!=witness.remaining)throw std::runtime_error("tagged annotation disagrees with shared pop");
}

bool preserves_tail(const Witness& base,const Witness& child,std::string& reason) {
    int head=std::max(1,base.links-2);
    if(child.links<base.links){reason="lost_link";return false;}
    if(child.points<=base.points){reason="no_score_gain";return false;}
    for(auto [id,stage]:base.stages){if(id<0)continue;auto found=child.stages.find(id);
        if(found==child.stages.end()){reason="lost_anchor";return false;}
        if(stage<=head&&found->second!=stage){reason="head_changed";return false;}
        if(stage>head&&found->second<=head){reason="tail_moved_to_head";return false;}}
    for(auto [id,stage]:child.stages)if(id>=1000&&stage<=head){reason="new_cell_in_head";return false;}
    reason="accepted";return true;
}
json witness_json(const Witness& w) {
    json anchors=json::array(),masks=json::array();for(auto [id,stage]:w.stages)anchors.push_back({id,stage});
    auto mask_copy=w.masks;for(int i=0;i<mask_copy.get_size();++i){auto f=mask_copy[i];masks.push_back(text::from_field(f));}
    auto remain=w.remaining;
    return {{"column",w.x},{"color",std::string(1,cell::to_char(cell::Type(w.color)))},{"key",w.key},
        {"links",w.links},{"points",w.points},{"headroom",w.headroom},{"stages",anchors},
        {"masks",masks},{"remaining",text::from_field(remain)},{"level","G"}};
}

json Planner::choose(const Observation& obs,bool goals,Limits limits) {
    Work work(limits);json result={{"decision",nullptr},{"score_probe_complete",false},{"goal_complete",false}};
    auto scoring=normal_scoring::find(obs.character);int depth=std::min(3,40-obs.t);
    try {
        std::vector<Node> layer={{obs.field,{},true,0,room(obs.field)}},prefixes;
        for(int d=0;d<depth;++d){std::vector<Node> next;std::optional<Fire> best;
            for(const auto& parent:layer){work.check();++work.expansions;
                for(auto a:legal(parent.field,obs.visible[d])){work.transition();Node child=parent;child.path.push_back(a);
                    auto drop=child.field.drop_piece(a.x,a.r,obs.visible[d],RULES);if(!drop){++work.rejected["drop_failed"];continue;}
                    auto masks=child.field.pop();auto copied=masks;auto score=normal_scoring::score(copied,*scoring);
                    child.discard+=drop->discarded;if(drop->discarded)++work.discarded;
                    if(child.field.is_dead(rule::FEVER)){++work.deaths;continue;}
                    child.min_room=std::min(child.min_room,room(child.field));
                    child.build=parent.build&&masks.get_size()==0&&drop->discarded==0&&normal_space::room(child.field,1);
                    if(score.count>=10){if(score.score>=obs.target){Fire fire{child,int(score.score),int(score.count)};
                        auto rank=[](const Fire& f){return std::make_tuple(-f.points,f.node.discard,path_key(f.node.path));};
                        if(!best||rank(fire)<rank(*best))best=fire;}else ++work.rejected["first_below_score"];continue;}
                    if(goals&&child.build)prefixes.push_back(child);next.push_back(std::move(child));
                }
            }
            if(best){result["decision"]=decision(obs,best->node.path,"score_fire");
                result["score_probe_complete"]=true;result["goal_complete"]=true;
                result["first_main_score"]=best->points;result["first_main_chain"]=best->chain;
                if(active){result["interrupted_goal"]=goal_json(*active,"score_fire_interrupt");active.reset();}
                result["stats"]=work.stats();return result;}
            layer=std::move(next);
        }
        result["score_probe_complete"]=true;
        if(!goals){result["goal_complete"]=true;result["stats"]=work.stats();return result;}
        auto consume=[&](const char* source){auto& g=*active;auto chosen=g.actions[g.next];
            std::vector<move::Placement> one{chosen};result["decision"]=decision(obs,one,source);++g.next;
            result["goal"]=goal_json(g,g.next==g.actions.size()?"completed":"active");result["goal_complete"]=true;
            if(g.next==g.actions.size())active.reset();};
        if(active){auto& g=*active;bool valid=obs.character==g.origin.character&&obs.t==g.origin.t+int(g.next)
                &&obs.phase==g.origin.phase+int(g.next)&&obs.since==g.origin.since+int(g.next)&&obs.maximum==g.origin.maximum;
            auto expected=g.next?g.after[g.next-1]:g.origin.field;if(expected!=obs.field)valid=false;
            for(size_t i=g.next;i<g.origin.visible.size();++i)if(obs.visible[i-g.next]!=g.origin.visible[i])valid=false;
            if(valid){auto a=g.actions[g.next];bool lock=false;for(auto p:legal(obs.field,obs.visible[0]))if(a.x==p.x&&a.r==p.r)lock=true;
                work.transition();auto copy=obs.field;auto drop=lock?copy.drop_piece(a.x,a.r,obs.visible[0],RULES):std::nullopt;
                if(!drop||drop->discarded||copy.pop_count()!=0||!normal_space::room(copy,1)||copy!=g.after[g.next])valid=false;}
            if(valid){consume("goal_continue");result["stats"]=work.stats();return result;}
            result["invalidated_goal"]=goal_json(g,"observation_or_safety_mismatch");active.reset();
        }
        std::vector<Witness> bases;
        for(int x=0;x<6;++x)for(int c=0;c<cell::COUNT-1;++c){auto w=geometric(obs.field,x,c,3,*scoring,work);if(w&&w->links>=4)bases.push_back(*w);}
        auto rank_base=[](const Witness& w){return std::make_tuple(-w.points,w.key,-w.headroom,w.x,w.color);};
        std::sort(bases.begin(),bases.end(),[&](const Witness&a,const Witness&b){return rank_base(a)<rank_base(b);});
        if(bases.empty()||bases[0].points>=obs.target){result["goal_skip"]=bases.empty()?"no_witness4":"geometric_target_already_met";
            result["goal_complete"]=true;result["stats"]=work.stats();return result;}
        if(bases.size()>3)bases.resize(3);for(auto& w:bases)trace_ids(obs.field,augment(obs.field,w),w);
        std::optional<Goal> best;std::optional<std::tuple<int,int,int,int,int,std::string,std::string>> best_rank;
        for(const auto& prefix:prefixes)for(const auto& base:bases){auto w=geometric(prefix.field,base.x,base.color,base.key,*scoring,work);
            if(!w){++work.rejected["lost_key"];continue;}if(w->points<=base.points||w->links<base.links){++work.rejected["no_score_or_link_gain"];continue;}
            trace_ids(obs.field,augment(prefix.field,*w),*w);std::string reason;
            if(!preserves_tail(base,*w,reason)){++work.rejected[reason];continue;}
            auto id=goal_id(obs,base,prefix.path);
            auto counted=prefix.field;
            auto rank=std::make_tuple(std::max(0,obs.target-w->points),w->key,int(prefix.path.size()),
                -prefix.min_room, -(74-int(counted.get_count())),path_key(prefix.path),id);
            if(!best_rank||rank<*best_rank){Goal g;g.origin=obs;g.base=base;g.result=*w;g.actions=prefix.path;g.id=id;
                g.kind=w->links>base.links?"append_link":"enlarge_tail_group";auto field=obs.field;
                for(size_t i=0;i<g.actions.size();++i){auto a=g.actions[i];field.drop_piece(a.x,a.r,obs.visible[i],RULES);field.pop();g.after.push_back(field);}
                best=std::move(g);best_rank=rank;}
        }
        result["goal_complete"]=true;
        if(best){active=std::move(best);consume("goal_new");}else result["goal_skip"]="no_admissible_tail_plan";
    }catch(const Exhausted& error){work.stopped=error.what();result["decision"]=nullptr;
        if(active){result["invalidated_goal"]=goal_json(*active,"budget_fallback");active.reset();}}
    result["stats"]=work.stats();return result;
}
}

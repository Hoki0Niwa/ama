#include "firstscore40_goal.h"
#include <iostream>
#include <set>
using namespace fever::research::firstscore40;
namespace {
void keys(const json& value,std::set<std::string> expected){
    if(!value.is_object())throw std::invalid_argument("expected object");
    std::set<std::string> actual;for(auto it=value.begin();it!=value.end();++it)actual.insert(it.key());
    if(actual!=expected)throw std::invalid_argument("unexpected or missing public request fields");
}
int integer(const json& value,int lo,int hi){if(!value.is_number_integer()||value<lo||value>hi)throw std::invalid_argument("integer out of range");return value.get<int>();}
Observation read(const json& j){
    keys(j,{"field","visible","character","placed_total","dropset_index","moves_since_chain","normal_chain_max"});
    Observation o;o.character=j.at("character").get<std::string>();
    if(o.character!="raffina"&&o.character!="rafisol")throw std::invalid_argument("target not defined for character");
    o.target=o.character=="raffina"?160520:166840;
    o.t=integer(j.at("placed_total"),0,39);o.phase=integer(j.at("dropset_index"),0,1000000);
    o.since=integer(j.at("moves_since_chain"),0,40);o.maximum=integer(j.at("normal_chain_max"),0,9);
    auto rows=j.at("field").get<std::vector<std::string>>();
    if(rows.size()!=14||rows[0]!="......")throw std::invalid_argument("empty row14 required");
    for(auto& row:rows)if(row.size()!=6||row.find_first_not_of("RYGB#.")!=std::string::npos)throw std::invalid_argument("invalid field");
    auto f=fever::text::to_field(rows);if(!f||f->is_dead(rule::FEVER))throw std::invalid_argument("invalid or dead field");o.field=*f;
    auto visible=j.at("visible").get<std::vector<std::string>>();if(visible.size()!=3)throw std::invalid_argument("exactly three visible pieces required");
    for(int i=0;i<3;++i){auto p=fever::text::to_piece(visible[i]);auto shape=dropset::drop_at(o.character,o.phase+i);
        if(!p||!shape||!fever::text::is_matching(*p,*shape))throw std::invalid_argument("visible shape disagrees with cycle");o.visible.push_back(*p);}return o;
}
}
int main(){Planner planner;std::string line;while(std::getline(std::cin,line)){if(line.empty())continue;
    try{auto request=json::parse(line);auto op=request.at("op").get<std::string>();
        if(op=="reset"){keys(request,{"op"});planner.reset();std::cout<<json{{"reset",true}}.dump()<<std::endl;continue;}
        keys(request,{"op","observation","work_budget_ms","transition_limit","witness_limit"});
        if(op!="score-probe"&&op!="goal-choose")throw std::invalid_argument("unknown operation");
        Limits limits;limits.wall_ms=request.at("work_budget_ms").get<double>();
        if(!std::isfinite(limits.wall_ms)||limits.wall_ms<0||limits.wall_ms>5000)throw std::invalid_argument("invalid work budget");
        limits.transitions=integer(request.at("transition_limit"),0,16000);limits.witnesses=integer(request.at("witness_limit"),0,48000);
        if(op=="score-probe")planner.reset();auto result=planner.choose(read(request.at("observation")),op=="goal-choose",limits);
        result["schema"]="ama.firstscore40.planner.v1";std::cout<<result.dump()<<std::endl;
    }catch(const std::exception& e){planner.reset();std::cout<<json{{"error",e.what()}}.dump()<<std::endl;}
}}

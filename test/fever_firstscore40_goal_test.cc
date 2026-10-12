#include "../fever/research/firstscore40_goal.h"
#include <stdexcept>
using namespace fever::research::firstscore40;
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
int main(){
    for(auto [name,target]:std::vector<std::pair<std::string,int>>{{"raffina",160520},{"rafisol",166840}}){
        auto table=fever::normal_scoring::find(name);check(fever::normal_scoring::pure(15,*table)==target,"pure15 scoring");
        avec<Field,19> masks;for(int i=0;i<14;++i){Field mask;for(int x=0;x<4;++x)mask.set_cell(x,0,cell::Type::RED);
            if(i==13)for(int x=0;x<4;++x)mask.set_cell(x,1,cell::Type::RED);masks.add(mask);}
        auto score=fever::normal_scoring::score(masks,*table);check(score.score==target+320,"14 tail8 scoring");
    }
    Witness base;base.links=4;base.points=1000;base.stages={{0,1},{1,2},{2,3},{3,4}};
    auto child=base;child.points=1200;child.stages[1000]=4;std::string reason;
    check(preserves_tail(base,child,reason),"tail group enlargement rejected");
    child.links=5;child.stages[1000]=5;check(preserves_tail(base,child,reason),"tail append rejected");
    child.stages[0]=2;check(!preserves_tail(base,child,reason)&&reason=="head_changed","head identity not protected");
    child=base;child.points=1200;child.stages[2]=2;check(!preserves_tail(base,child,reason),"tail moved to head");
    child=base;child.points=1200;child.stages.erase(3);check(!preserves_tail(base,child,reason),"lost original tail anchor");
    child=base;child.points=1200;child.stages[1000]=1;check(!preserves_tail(base,child,reason),"new cell in head");
    child=base;check(!preserves_tail(base,child,reason),"no gain accepted");
    for(bool garbage:{false,true}){
        Field origin;for(int x=0;x<3;++x)origin.set_cell(x,0,cell::Type::RED);
        if(garbage)origin.set_cell(3,0,cell::Type::GARBAGE);
        auto augmented=origin;int x=garbage?2:3;int y=augmented.get_height(x);augmented.set_cell(x,y,cell::Type::RED);
        Witness w;w.x=x;w.color=0;w.key=1;w.remaining=augmented;w.masks=w.remaining.pop();w.links=w.masks.get_size();
        trace_ids(origin,augmented,w);check(w.links==1,"trace fixture must fire");
        check(w.stages.at(0)==1&&w.stages.at(1)==1&&w.stages.at(2)==1&&w.stages.at(-1)==1,"wrong tag stages");
        check(w.remaining.is_empty(),"adjacent nuisance was not removed");
    }
    std::cout<<"firstscore40 native checks passed\n";
}

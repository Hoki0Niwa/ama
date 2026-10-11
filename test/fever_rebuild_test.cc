#include "../fever/rebuild.h"
#include "../fever/fire.h"
#include "../fever/text.h"
#include "../fever_battle/transition.h"
#include "../fever_battle/counter_order.h"
#include <iostream>
#include <stdexcept>

void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }

int main() {
    using namespace fever;
    check(fever_battle::prefer_full_return(36000,600,24000,300),"full return saturates at a normal-board kill amount");
    check(!fever_battle::prefer_full_return(24000,300,36000,600),"faster weak return replaces a larger sufficient return");
    check(fever_battle::prefer_full_return(36000,300,36000,600),"equal full returns do not prefer earlier completion");
    fever_battle::Bonuses bonuses(json{{"color", {0,0,2,4,8}}, {"group", {0,0,0,0,0,1,2,3,4,5,6,8}},
                                      {"multiplier_min",1}, {"multiplier_max",999}});
    // Mixed colors, excess groups and adjacent nuisance, repeated over every
    // chain position and all characters: compare the existing battle scorer.
    avec<Field,19> masks;
    for (int i = 0; i < 19; ++i) {
        Field mask;
        for (int x=0;x<4;++x) mask.set_cell(x,0,cell::Type::RED);
        if (i%2) for (int y=0;y<5;++y) mask.set_cell(5,y,cell::Type::BLUE);
        if (i%3==0) mask.set_cell(0,1,cell::Type::GARBAGE);
        masks.add(mask);
    }
    for (const auto& entry : normal_scoring::ENTRIES) {
        i64 expected=0;
        for (int i=0;i<19;++i) expected += fever_battle::score_link(masks[i],entry.powers[i],bonuses).points;
        check(normal_scoring::score(masks,entry).score==expected,"normal score differs from battle scorer");
        check(normal_scoring::pure(2,entry)==40+40*entry.powers[1],"pure score uses character table");
    }
    check(normal_scoring::find("paprisu")->powers[15]==765,"high character multiplier preserved");

    auto seed = *text::to_field(std::vector<std::string>{"......","......","......","......","......","......","......",
        ".....R",".....R",".....B",".....B","...BRR","..YYBB","..YBRR"});
    Configs cfg; cfg.normal=normal_scoring::find("arle"); cfg.rules.special_moves=true; cfg.rules.margin=1;
    beam::eval::Weight w; w.chain=1500; w.key=-200; w.y=289; w.score=400;
    auto pair=*text::to_piece("2:RY");
    auto big=*text::to_piece("0:R");
    auto triple=*text::to_piece("L:RRG");
    auto quad=*text::to_piece("4:RGRG");
    for (auto piece : {pair,big,triple,quad}) {
        auto features=rebuild::inspect(seed, Queue{piece},w,cfg);
        auto actual=fire::best_now(seed,piece,cfg.rules,cfg.normal);
        check(actual.has_value(),"no safe fixture placement");
        check(features.visible_chain==actual->chain.count,"visible potential must be actual Piece chain");
        check(features.expanded<=move::generate(seed,piece,cfg.rules).get_size(),"unbounded one-piece inspection");
    }
    auto features=rebuild::inspect(seed,Queue{triple,quad},w,cfg);
    auto actual=fire::best_visible(seed,Queue{triple,quad},cfg.rules,cfg.normal);
    check(features.visible_chain<=actual->chain.count,"bounded inspection claims impossible chain");
    check(features.expanded<=7*64,"two-piece inspection unbounded");

    // No NEXT is an unknown future, not an imagined color that can fire.
    auto unknown=rebuild::inspect(seed,{},w,cfg);
    check(unknown.visible_chain==0 && unknown.safe==0 && unknown.expanded==0,"unknown piece was guessed");

    // Small clears that expose/remove nuisance are eligible cleanup; a
    // geometric chain alone never authorizes firing a protected main.
    cfg.width=20; cfg.depth=3; cfg.trigger=14; cfg.panic_count=100; cfg.preserve_build=true; cfg.rebuild=true;
    cfg.construction_scoring=true;
    auto choice=think(seed,Queue{pair},*dropset::find("arle"),0,w,cfg);
    check(choice && !choice->fire,"unfinished main was fired by reconstruction");
    auto after=seed; after.drop_piece(choice->placement.x,choice->placement.r,pair,cfg.rules);
    check(after.pop().get_size()<=2,"reconstruction consumed unfinished main");
    check(!choice->reconstruction.is_null(),"reconstruction not connected");

    Field dirty;
    for (int y=0;y<3;++y) { dirty.set_cell(0,y,cell::Type::GREEN); dirty.set_cell(1,y,cell::Type::GARBAGE); }
    auto cleanup=*text::to_piece("2:GB");
    Result candidates;
    Candidate build, clear; build.placement={2, direction::Type::UP}; clear.placement={0, direction::Type::UP};
    candidates.candidates={build,clear};
    auto diagnostic=rebuild::rank(dirty,Queue{cleanup,pair},candidates,w,cfg);
    check(candidates.candidates.front().placement==clear.placement,"useful nuisance cleanup not preferred");
    check(diagnostic["cleanup_links"]==1 && diagnostic["useful_cleanup"]==true,"cleanup proof missing");
    std::cout << "checks passed\n";
}

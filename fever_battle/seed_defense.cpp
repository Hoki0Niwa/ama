#include "search.h"
#include "transition.h"
#include "physics.h"
#include "../fever/text.h"
#include <chrono>
#include <functional>
#include <limits>

namespace fever_battle {
using json = nlohmann::json;
// Can a regular seed still fire after the packet actually drops on a
// nonclearing placement? Search the real board, colors and special shapes;
// no seed-family-specific guess is used. Any possible counter is favorable
// to the opponent when the partial-row cursor is unknown.
json seed_defense(Field field, const json& request) {
    auto rules = rule::FEVER; rules.special_moves = true;
    const int target = number(request, "seed_chain", 3, 15);
    const auto queue = request.at("queue").get<std::vector<std::string>>();
    if (queue.empty() || queue.size() > 3) throw std::invalid_argument("seed defense requires visible queue");
    std::vector<piece::Piece> pieces;
    for (const auto& text : queue) {
        auto p = fever::text::to_piece(text);
        if (!p) throw std::invalid_argument("invalid defense piece");
        pieces.push_back(*p);
    }
    const auto powers = request.at("powers").get<std::vector<int>>();
    const Bonuses bonuses(request.at("bonuses"));
    const int maximum = number(request, "max_nodes", 1, 1000000);
    int expanded = 0;
    struct Cutoff {};
    const auto tick = [&] {
        if (++expanded > maximum) throw Cutoff{};
    };
    const auto score = [&](avec<Field,19>& masks) {
        i64 sum=0;
        for (int k=0;k<masks.get_size();++k) sum += score_link(masks[k],powers.at(k),bonuses).points;
        return sum;
    };
    i64 before_points=0;
    // The immediate fire can suppress this piece's drop. Its score is
    // diagnostic; the after-drop proof below is deliberately separate.
    auto initial=field;
    auto immediate=move::generate(initial,pieces[0],rules);
    for (int i=0;i<immediate.get_size();++i) {
        auto next=field;
        if (!next.drop_piece(immediate[i].x,immediate[i].r,pieces[0],rule::FEVER)) continue;
        auto masks=next.pop();
        if (masks.get_size()>=target && !next.is_dead(rule::FEVER)) before_points=std::max(before_points,score(masks));
    }
    json profiles=json::array();
    for(int n=0;n<=30;++n) profiles.push_back({{"amount",n},{"checked",false},{"regular_after_drop",false},{"counter_points",0}});
    bool cutoff=false;
    for(const auto& amount_value:request.at("amounts")) {
        const int amount=number(json{{"v",amount_value}},"v",0,30);
        bool safe=false; i64 counter=0; int counter_chain=0; bool counter_clear=false; bool interrupted=false;
        std::function<bool(Field,int,bool)> visit;
        visit=[&](Field board,int depth,bool landed) {
            if (depth>=int(pieces.size()) || board.is_dead(rule::FEVER)) return false;
            auto moves=move::generate(board,pieces[depth],rules);
            for(int i=0;i<moves.get_size();++i) {
                tick(); auto next=board;
                if(!next.drop_piece(moves[i].x,moves[i].r,pieces[depth],rule::FEVER)) continue;
                auto masks=next.pop();
                if(next.is_dead(rule::FEVER)) continue;
                if(masks.get_size()) {
                    if(landed && masks.get_size()>=target) {
                        safe=true; const auto points=score(masks);
                        if(points>counter) {counter=points;counter_chain=masks.get_size();counter_clear=next.is_empty();}
                    }
                    continue;
                }
                if(landed) { if(visit(next,depth+1,true)) return true; }
                else {
                    bool found=false;
                    if(request.value("unknown_garbage_phase",true))
                        each_remainder_drop(next,amount,[&](Field variant){ if(!found) found=visit(variant,depth+1,true); });
                    else { drop_nuisance(next,amount,number(request,"garbage_phase",0,5)); found=visit(next,depth+1,true); }
                    if(found) return true;
                }
            }
            return false;
        };
        try { visit(field,0,false); }
        catch(const Cutoff&) { cutoff=true; interrupted=true; }
        profiles[amount]={{"amount",amount},{"checked",!interrupted || safe},{"regular_after_drop",safe},{"counter_points",counter},
            {"counter_complete",!interrupted},{"counter_chain",counter_chain},{"counter_all_clear",counter_clear}};
        if(interrupted) break;
    }
    return {{"profiles",profiles},{"before_drop_points",before_points},{"expanded",expanded},{"cutoff",cutoff},
        {"visible",pieces.size()},{"model","actual_board_visible_queue_after_nonclear_drop"}};
}
}

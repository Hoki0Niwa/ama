#include "gauge_wait.h"
#include "../fever/text.h"
#include "color_needs.h"
#include "transition.h"
#include <bit>
#include <chrono>
#include <tuple>

namespace fever_battle {
using json = nlohmann::json;
namespace {
struct State { Field field; int fixed, flying, gauge; i64 remainder; };
struct Value {
    bool alive = false; int gauge = 0, popped = 0, steps = 0, height = 0, rough = 0, needed_loss = 0;
    auto rank() const { return std::tuple(alive, gauge, -needed_loss, -popped, -steps, -height, -rough); }
};
struct Edge { State state; int x, r, popped; bool clear; int needed_loss; };
struct Exhausted {};
class Search {
public:
    std::vector<piece::Piece> pieces;
    std::array<int,19> power{};
    Bonuses bonuses;
    int gain, rate, width;
    std::array<int,4> reserves{};
    int root_mainline = 0;
    rule::Rule rules = rule::FEVER;
    std::chrono::steady_clock::time_point deadline;
    int expanded = 0;
    void check() {
        if (expanded >= 60000 || std::chrono::steady_clock::now() >= deadline) throw Exhausted{};
    }
    Value leaf(State s) {
        u8 heights[6]; s.field.get_heights(heights);
        int rough = 0; for (int x=0;x<6;++x) rough += heights[x]*heights[x];
        return {!s.field.is_dead(rules), s.gauge, 0, 0, std::max(heights[2],heights[3]), rough};
    }
    std::vector<Edge> edges(State s, int depth) {
        std::vector<Edge> out;
        if (s.field.is_dead(rules)) return out;
        auto moves = move::generate(s.field, pieces[depth], rules);
        for (int k=0;k<moves.get_size();++k) {
            check(); ++expanded;
            auto next = s;
            if (!next.field.drop_piece(moves[k].x,moves[k].r,pieces[depth],rules))
                throw std::runtime_error("generated gauge placement failed");
            auto masks = next.field.pop(); int popped = 0, needed_loss = 0;
            for (int link=0;link<masks.get_size();++link) {
                for (int c=0;c<cell::COUNT-1;++c)
                    needed_loss += masks[link].data[c].get_count() * reserves[c];
                const auto scored = score_link(masks[link], power[link], bonuses);
                popped += scored.cells;
                i64 points = scored.points;
                i64 amount = (points+next.remainder)/rate;
                next.remainder = (points+next.remainder)%rate;
                if (next.fixed+next.flying && !amount) amount=1;
                int offset = int(std::min<i64>(next.fixed+next.flying,amount));
                int fixed = std::min(next.fixed,offset);
                next.fixed -= fixed; next.flying -= offset-fixed;
                if (offset) next.gauge = std::min(7,next.gauge+gain);
            }
            if (depth == 0)
                needed_loss += std::max(0, root_mainline - color_needs(next.field).chain) * 4;
            out.push_back({next,moves[k].x,int(moves[k].r),popped,masks.get_size()!=0,needed_loss});
        }
        return out;
    }
    Value continuation(Edge e, int depth, int limit) {
        auto best = leaf(e.state);
        // Entry follows the chain; never search normal NEXT on a Fever seed.
        if (best.alive && e.state.gauge<7 && !(e.clear && e.state.field.is_empty())) {
            const int drop = e.clear ? 0 : std::min(30,e.state.fixed);
            bool first = true;
            each_remainder_drop(e.state.field, drop, [&](Field board) {
                auto next=e.state; next.field=board;
                next.fixed-=drop;
                auto value = leaf(next);
                if (value.alive && depth+1<limit) value=solve(next,depth+1,limit);
                if (first || value.rank()<best.rank()) best=value;
                first=false;
            });
        }
        best.popped+=e.popped; best.needed_loss+=e.needed_loss; ++best.steps;
        return best;
    }
    Value solve(State state,int depth,int limit) {
        auto choices=edges(state,depth);
        if (choices.empty()) {auto value=leaf(state);value.alive=false;return value;}
        std::stable_sort(choices.begin(),choices.end(),[&](const Edge& a,const Edge& b) {
            auto av=leaf(a.state);av.popped=a.popped;av.needed_loss=a.needed_loss;
            auto bv=leaf(b.state);bv.popped=b.popped;bv.needed_loss=b.needed_loss;
            return av.rank()>bv.rank();
        });
        if (choices.size()>size_t(width)) choices.resize(width);
        Value best; bool first=true;
        for (const auto& e:choices) {
            check(); auto value=continuation(e,depth,limit);
            if (first || value.rank()>best.rank()) best=value;
            first=false;
        }
        return best;
    }
};
}
json gauge_wait(Field field,const json& request) {
    Search search;
    search.gain=number(request,"gain",1,7); search.rate=number(request,"target_point",1,100000);
    search.width=number(request,"width",1,24);
    int budget=number(request,"budget_ms",1,1000);
    search.rules.plain_pairs=true;
    const auto queue=request.at("queue").get<std::vector<std::string>>();
    if (queue.empty() || queue.size()>3) throw std::invalid_argument("visible queue only");
    for (const auto& text:queue) {
        auto piece=fever::text::to_piece(text);
        if (!piece) throw std::invalid_argument("invalid visible piece");
        search.pieces.push_back(*piece);
    }
    const auto powers=request.at("powers");
    if (!powers.is_array() || powers.size()!=19) throw std::invalid_argument("19 normal powers required");
    for (int k=0;k<19;++k) search.power[k]=powers[k].get<int>();
    search.bonuses=Bonuses(request.at("bonuses"));
    State root{field,number(request,"confirmed",0,1000000000),number(request,"unconfirmed",0,1000000000),
        number(request,"gauge",0,6),number(request,"remainder",0,1000000000)};
    auto needs=color_needs(field); search.reserves=needs.reserve; search.root_mainline=needs.chain;
    search.deadline=std::chrono::steady_clock::now()+std::chrono::milliseconds(budget);
    json result=json::array();int completed=0;bool cutoff=false;
    try {
        auto roots=search.edges(root,0);
        if (request.contains("allowed")) {
            const auto allowed=request.at("allowed");
            std::erase_if(roots,[&](const Edge& e) {
                for (const auto& a:allowed) if (a.at("x")==e.x && a.at("r")==std::string(1,fever::text::from_direction(direction::Type(e.r)))) return false;
                return true;
            });
        }
        for (int limit=1;limit<=int(queue.size());++limit) {
            json layer=json::array();
            for (const auto& edge:roots) {
                search.check();auto value=search.continuation(edge,0,limit);
                layer.push_back({{"x",edge.x},{"r",std::string(1,fever::text::from_direction(direction::Type(edge.r)))},
                    {"survives",value.alive},{"gauge_after",edge.state.gauge},{"projected_gauge",value.gauge},
                    {"popped",edge.popped},{"projected_popped",value.popped},{"steps",value.steps},
                    {"needed_color_consumed",edge.needed_loss},{"projected_needed_color_consumed",value.needed_loss},
                    {"central_height",value.height},{"roughness",value.rough}});
            }
            result=std::move(layer);completed=limit;
        }
    } catch (const Exhausted&) {cutoff=true;}
    return {{"candidates",result},{"completed_depth",completed},{"visible",queue.size()},
        {"color_needs",needs.describe(search.pieces,0)},
        {"expanded",search.expanded},{"cutoff",cutoff},{"unconfirmed_not_scheduled",true}};
}
}

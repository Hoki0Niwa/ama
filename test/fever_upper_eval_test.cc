#include "../fever/search.h"
#include <iostream>
#include <stdexcept>
void check(bool ok, const char* msg) { if (!ok) throw std::runtime_error(msg); }

static int stack_eval(const std::array<int, 6>& heights, int weight, bool normal = true) {
    beam::node::Data node;
    for (int x = 0; x < 6; ++x)
        for (int y = 0; y < heights[x]; ++y)
            node.field.set_cell(x, y, cell::Type::GARBAGE);
    fever::Configs configs;
    if (normal) configs.normal = fever::normal_scoring::find("satan");
    configs.stack_balance = weight;
    fever::evaluate(node, beam::eval::Weight{}, configs);
    return node.score.eval;
}

int main() {
    beam::eval::Weight w;
    w.waste_14 = -500;
    json set = w;
    set.erase("waste_14");
    check(fever::read_weights(set).waste_14 == 0, "removed key accepted");
    set["waste_14"] = -999;
    check(fever::read_weights(set).waste_14 == 0, "legacy row14 ignored");
    fever::Configs cfg;
    for (int x = 0; x < 6; ++x) for (int h = 11; h <= 13; ++h) {
        beam::node::Data n;
        for (int y = 0; y < h; ++y) n.field.set_cell(x, y, cell::Type::GARBAGE);
        cfg.sustained_min_chain=12;
        check(fever::cycle_rate({1,1000000},1,cfg)==0,"large-chain floor excludes chase");
        check(fever::cycle_rate({12,100000},1,cfg)>fever::cycle_rate({12,100000},8,cfg),"extra shaping delays reduce rate");
        n.field.row14 = 63;
        fever::evaluate(n, w, cfg);
        check(n.score.eval == 0, "legacy upper rows disabled");
    }
    beam::node::Data n;
    for (int x : {1,4}) for (int y=0;y<13;++y) n.field.set_cell(x,y,cell::Type::GARBAGE);
    fever::read_upper_weights(cfg,json{{"upper_12",-999},{"upper_13",-999}});
    fever::evaluate(n,w,cfg);
    check(n.score.eval==0,"launcher snapshot cannot restore disabled terms");
    n.field.row14 = 63;
    beam::eval::evaluate(n,w);
    check(n.score.eval != 0, "Tsu row14 evaluation preserved");
    const std::array<int, 6> one_side{8, 7, 5, 2, 1, 1};
    auto reflected = one_side;
    std::reverse(reflected.begin(), reflected.end());
    check(stack_eval({6, 4, 2, 0, 0, 0}, 50) == -450, "early stack penalty uses full weight");
    check(stack_eval(one_side, 50) == -371, "stack penalty fades as the board fills");
    check(stack_eval({10, 9, 7, 4, 3, 3}, 50) == -92, "same terrain difference costs less on a fuller board");
    check(stack_eval({11, 10, 8, 5, 4, 2}, 50) == 0, "stack penalty ends at the configured cell count");
    check(stack_eval(reflected, 50) == stack_eval(one_side, 50), "stack penalty is reflection invariant");
    check(stack_eval({0, 1, 9, 9, 1, 0}, 50) == -285, "balanced column sums cannot hide a central peak");
    check(stack_eval({3, 3, 3, 1, 1, 1}, 50) == 0, "small height and side differences are allowed");
    check(stack_eval(one_side, 0) == 0, "stack penalty is disabled at zero weight");
    check(stack_eval(one_side, 50, false) == 0, "legacy scoring is unaffected by stack balance");
    std::cout << "checks passed\n";
}

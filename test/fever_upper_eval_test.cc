#include "../fever/search.h"
#include <iostream>
#include <stdexcept>
void check(bool ok, const char* msg) { if (!ok) throw std::runtime_error(msg); }
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
    std::cout << "checks passed\n";
}

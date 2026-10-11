#include "evaluation.h"

namespace fever {
Potential potential(Field field, const beam::eval::Weight& w, const Configs& configs) {
    Potential best;
    i32 highest = INT32_MIN;
    u8 heights[6]; field.get_heights(heights);
    // Fever reachability is checked with actual Pieces at the root. Do not
    // inherit the Tsu pair-only wall bound in this cheap geometric estimate.
    for (int x = 0; x < 6; ++x) {
        for (int c = 0; c < cell::COUNT-1; ++c) {
            auto plan = field;
            for (int key = 1; key <= std::min(3, 12-int(heights[x])); ++key) {
                plan.set_cell(x, heights[x]+key-1, cell::Type(c));
                if (plan.data[c].get_mask_group_4(x, heights[x]).get_count() < 4) continue;
                auto remain = plan;
                auto masks = remain.pop();
                if (masks.get_size() > 1) {
                    auto scored = configs.normal ? normal_scoring::score(masks, *configs.normal) : chain::get_score(masks);
                    auto [link2, link3] = beam::eval::get_link_23(remain);
                    i64 value = i64(scored.count)*w.chain + int(heights[x])*w.y + key*w.key
                        + beam::eval::get_chi(heights, x)*w.chi + link2*w.link_2 + link3*w.link_3;
                    if (configs.normal && w.score) {
                        const int bonus = scored.score - normal_scoring::pure(scored.count, *configs.normal);
                        // A character with high tail powers must not make a
                        // few excess cells outweigh several actual links in
                        // the geometric beam. Normalize the actual bonus by
                        // that character's same-length pure chain; final root
                        // ranking still uses uncapped actual normal points.
                        value += i64(bonus)*w.score/std::max(1000, normal_scoring::pure(scored.count, *configs.normal));
                        // L/J/4 pieces inherently spend extra cells. They
                        // cannot each be turned into a quarter of a fictitious
                        // tail link at its full character multiplier. Charge
                        // geometric chain efficiency, not that Tsu opportunity
                        // cost; still credit the real multi/group bonus above.
                        // Five/six-cell links occur naturally with irregular
                        // pieces. Penalize only larger groups geometrically.
                        value -= i64(normal_scoring::excess_cells(masks))*w.chain/4;
                    }
                    if (value > highest) {
                        highest = i32(value);
                        best = {scored.count, scored.score, key, i32(value)};
                    }
                }
                break;
            }
        }
    }
    return best;
}

void evaluate_normal(beam::node::Data& node, const beam::eval::Weight& w, const Configs& configs) {
    // Reuse shared terrain helpers, not its Tsu quiet search (which would
    // traverse the same board again even with every quiet weight set to zero).
    u8 heights[6]; node.field.get_heights(heights);
    node.score.eval = beam::eval::get_shape(heights)*w.shape
        + beam::eval::get_well(heights)*w.well + beam::eval::get_bump(heights)*w.bump
        + node.field.data[int(cell::Type::GARBAGE)].get_count()*w.nuisance
        + (std::max(int(heights[0]+heights[1]), int(heights[3]+heights[4]+heights[5]))-int(heights[2]))*w.side;
    if (w.form > 0) {
        auto garbage = node.field.data[int(cell::Type::GARBAGE)];
        garbage.data &= _mm_set_epi16(0,0,0,0,0xF,0xF,0xF,0xF);
        int form_score = 0;
        if (garbage.get_count() == 0) {
            form_score = -100;
            for (int i=0;i<beam::form::COUNT;++i)
                form_score = std::max(form_score,beam::form::evaluate(node.field,heights,beam::form::list[i]));
        }
        node.score.eval += form_score*w.form;
    }
    auto [link2, link3] = beam::eval::get_link_23(node.field);
    node.score.eval += link2*w.link_2 + link3*w.link_3;
    node.score.eval += potential(node.field, w, configs).value;
}
}

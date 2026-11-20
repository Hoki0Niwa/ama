#include "evaluation.h"

namespace fever {
Potential potential(Field field, const beam::eval::Weight& w, const Configs& configs) {
    Potential best;
    i32 highest = INT32_MIN;
    int near_chain = 0;
    u8 heights[6]; field.get_heights(heights);
    // Fever reachability is checked with actual Pieces at the root. Do not
    // inherit the Tsu pair-only wall bound in this cheap geometric estimate.
    // Two shortcuts that skip only trials the loop below would discard anyway (this estimate is most of the
    // search's time): a color absent next to the key cells, and a trigger that clears with nothing above it.
    const FieldBit occupied = field.get_mask();
    // The one-link shortcut assumes nothing pops before the keys land.
    const bool settled = field.row14 == 0 && field.get_mask_pop().get_mask().is_empty();
    for (int x = 0; x < 6; ++x) {
        const int keys = std::min(3, 12-int(heights[x]));
        if (keys <= 0) continue;
        // With none of its puyos next to the cells the keys can take, a color cannot reach four with three keys.
        FieldBit column;
        for (int key = 0; key < keys; ++key) column.set_bit(x, heights[x]+key);
        const FieldBit near = column.get_expand().get_mask_12();
        for (int c = 0; c < cell::COUNT-1; ++c) {
            if (_mm_testz_si128(field.data[c].data, near.data)) continue;
            auto plan = field;
            for (int key = 1; key <= keys; ++key) {
                plan.set_cell(x, heights[x]+key-1, cell::Type(c));
                if (plan.data[c].get_mask_group_4(x, heights[x]).get_count() < 4) continue;
                if (settled) {
                    // Only this group pops first. If nothing stands above what it clears (with the garbage next
                    // to it), nothing falls and the chain is one link, which scores nothing here.
                    FieldBit removed = plan.data[c].get_mask_group(x, heights[x]);
                    removed.data |= removed.get_expand().data & field.data[int(cell::Type::GARBAGE)].data;
                    const __m128i lowest = _mm_and_si128(removed.data, _mm_sub_epi16(_mm_setzero_si128(), removed.data));
                    const __m128i above = _mm_andnot_si128(
                        _mm_sub_epi16(_mm_slli_epi16(lowest, 1), _mm_set1_epi16(1)), _mm_set1_epi16(-1));
                    if (_mm_testz_si128(_mm_andnot_si128(removed.data, occupied.data), above)) break;
                }
                auto remain = plan;
                auto masks = remain.pop();
                if (masks.get_size() > 1) {
                    auto scored = configs.normal ? normal_scoring::score(masks, *configs.normal) : chain::get_score(masks);
                    if (key<=2) near_chain=std::max(near_chain,scored.count);
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
    best.near_chain=near_chain;
    return best;
}

void evaluate_normal(beam::node::Data& node, const beam::eval::Weight& w, const Configs& configs, int* near_chain) {
    // Reuse shared terrain helpers, not its Tsu quiet search (which would
    // traverse the same board again even with every quiet weight set to zero).
    u8 heights[6]; node.field.get_heights(heights);
    node.score.eval = beam::eval::get_shape(heights)*w.shape
        + beam::eval::get_well(heights)*w.well + beam::eval::get_bump(heights)*w.bump
        + node.field.data[int(cell::Type::GARBAGE)].get_count()*w.nuisance
        + (std::max(int(heights[0]+heights[1]), int(heights[3]+heights[4]+heights[5]))-int(heights[2]))*w.side;
    if (configs.stack_balance > 0) {
        const int left = heights[0] + heights[1] + heights[2];
        const int right = heights[3] + heights[4] + heights[5];
        const int cells = left + right;
        const int fade_end = configs.stack_balance_end_cells;
        if (cells < fade_end) {
            const int highest = *std::max_element(heights, heights + 6);
            const int imbalance = std::max(0, std::abs(left - right) - 6);
            // Allow a column three rows above the mean before charging excess height.
            const int excess = std::max(0, 6 * highest - cells - 18) / 2;
            const int fade_cells = fade_end - std::max(cells, Configs::stack_balance_full_cells);
            node.score.eval -= (imbalance + excess) * configs.stack_balance * fade_cells
                / (fade_end - Configs::stack_balance_full_cells);
        }
    }
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
    const auto held=potential(node.field, w, configs);
    node.score.eval += held.value;
    if (near_chain) *near_chain=held.near_chain;
}
}

#include "eval.h"

namespace beam
{

namespace eval
{

// Evaluates the position
void evaluate(node::Data& node, const Weight& w)
{
    node.score.eval = 0;

    u8 heights[6];
    node.field.get_heights(heights);

    // Human form pattern matching
    if (w.form > 0) {
        i32 form = -100;

        // Stop pattern matching if we have garbage puyo
        auto mask_garbage = node.field.data[static_cast<i32>(cell::Type::GARBAGE)];
        mask_garbage.data &= _mm_set_epi16(0, 0, 0, 0, 0xF, 0xF, 0xF, 0xF);

        if (mask_garbage.get_count() > 0) {
            form = 0;
        }
        else {
            // Find the best matching form
            for (i32 i = 0; i < form::COUNT; ++i) {
                form = std::max(form, form::evaluate(node.field, heights, form::list[i]));
            }
        }

        node.score.eval += form * w.form;
    }

    // Quiescence search
    i32 q = INT32_MIN;

    auto search = w.score != 0 ? quiet::search : quiet::search_count;
    search(node.field, 3, [&] (quiet::Result quiet) {
        i32 q_score = 0;

        // Potential chain
        q_score += quiet.chain.count * w.chain;

        // Trigger height
        q_score += heights[quiet.x] * w.y;

        // Key puyos needed
        q_score += quiet.key * w.key;

        // Space for stretching chain
        i32 chi = eval::get_chi(heights, quiet.x);
        q_score += chi * w.chi;

        // Remaining connection
        auto [link_2, link_3] = eval::get_link_23(quiet.remain);
        q_score += link_2 * w.link_2;
        q_score += link_3 * w.link_3;

        // Resources: puyos popped beyond 4 per link early in the chain are worth almost nothing in Tsu,
        // while the same puyos spent on the tail (a longer chain, a multi-color or a large last pop)
        // are worth a full link; the bonus is what the planned chain really scores above 4 per link
        if (w.score != 0) {
            i32 bonus = quiet.chain.score - eval::get_score_pure(quiet.chain.count);
            i32 loss = eval::get_score_loss(quiet.popped, quiet.chain.count);
            q_score += i32((i64(bonus - loss) * w.score) / 1000);
        }

        // Updates the best q score and plan
        q = std::max(q, q_score);
    });

    if (q > INT32_MIN) {
        node.score.eval += q;
    }

    // Field's shape
    i32 shape = eval::get_shape(heights);
    node.score.eval += shape * w.shape;

    // Avoids wells
    i32 well = eval::get_well(heights);
    node.score.eval += well * w.well;

    // Avoids bumps
    i32 bump = eval::get_bump(heights);
    node.score.eval += bump * w.bump;

    // Puyo connections
    auto [link_2, link_3] = eval::get_link_23(node.field);
    node.score.eval += link_2 * w.link_2;
    node.score.eval += link_3 * w.link_3;

    // Avoids wasting space on the 14th row
    i32 waste_14 = eval::get_waste_14(node.field.row14);
    node.score.eval += waste_14 * w.waste_14;

    // Avoids garbage puyo
    node.score.eval += node.field.data[static_cast<u8>(cell::Type::GARBAGE)].get_count() * w.nuisance;

    // Field side bias
    i32 height_left = heights[0] + heights[1];
    i32 height_right = heights[3] + heights[4] + heights[5];
    node.score.eval += (std::max(height_left, height_right) - i32(heights[2])) * w.side;
};

// Evaluates the actions that led to this position
void action(node::Data& node, i32 tear, i32 waste, const Weight& w)
{
    // Avoids tearing
    node.score.action += tear * w.tear;

    // Avoids wasting resource by popping puyos
    node.score.action += waste * w.waste;
};

// Returns how close the field's shape is to the ideal shape
i32 get_shape(u8 heights[6])
{
    i32 shape = 0;

    // We define the ideal field shape here:
    // ......
    // ......
    // ......
    // ###...
    // ###...
    // ######
    // ######
    // ######
    const i32 shape_coef[6] = { 1, 1, 1, -1, -1, -1 };

    i32 height_avg = 0;

    for (i32 i = 0; i < 6; ++i) {
        height_avg += heights[i];
    }

    height_avg = height_avg / 6;

    for (i32 i = 0; i < 6; ++i) {
        shape += std::abs(i32(heights[i]) - height_avg - shape_coef[i]);
    }

    return shape;
};

// Returns the Tsu score of a chain popping exactly 4 puyos per link
i32 get_score_pure(i32 count)
{
    i32 score = 0;

    for (i32 i = 0; i < count && i < 19; ++i) {
        score += 40 * i32(std::clamp(chain::POWER[i], 1U, 999U));
    }

    return score;
};

// Returns the opportunity cost of over-sized links
// Every puyo popped beyond 4 per link could instead have been a quarter of one more link at the end
// of the chain, worth 10 * POWER[count] points; what the puyo really earned where it is (about
// 10 * POWER[i] for a 5th puyo in link i, far more for a multi-color last pop) is part of the chain's
// score and is credited through the bonus, so a puyo spent on the tail nets about zero and a puyo
// spent on an early link nets almost the whole cost
i32 get_score_loss(const u8 popped[19], i32 count)
{
    if (count < 2) {
        return 0;
    }

    i32 tail = 10 * i32(chain::POWER[std::min(count, 18)]);
    i32 loss = 0;

    for (i32 i = 1; i < count && i < 19; ++i) {
        i32 excess = i32(popped[i]) - 4;

        if (excess > 0) {
            loss += excess * tail;
        }
    }

    return loss;
};

};

};

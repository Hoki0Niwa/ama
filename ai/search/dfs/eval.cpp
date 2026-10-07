#include "eval.h"

namespace dfs
{

namespace eval
{


// Evalutes a field
Result evaluate(Field& field, i32 tear, i32 waste, const Weight& w)
{
    i32 eval = 0;

    i32 count = field.get_count();

    // Quiescence search
    // Searching past the 2 given puyo pairs by dropping puyos until there aren't any chains left
    // This estimates the potential of the field
    auto plan = field;

    i32 q = INT32_MIN;
    i32 q_max = INT32_MIN;

    quiet::search(field, 16, 3, [&] (quiet::Result quiet) {
        i32 q_score = 0;

        u8 heights[6];
        quiet.plan.get_heights(heights);
        heights[quiet.x] = field.get_height(quiet.x);

        // Potential chain
        q_score += quiet.chain.count * w.chain;

        // Trigger height
        q_score += i32(heights[quiet.x]) * w.y;

        // Key puyos needed
        i32 key = quiet.plan.get_count() - count;
        q_score += key * w.key;

        // Space for stretching chain
        i32 chi = eval::get_chi(heights, quiet.x);
        q_score += chi * w.chi;

        // Remaining connections
        auto [link_2, link_3] = eval::get_link_23(quiet.remain);
        q_score += link_2 * w.link_2;
        q_score += link_3 * w.link_3;

        // Updates the best q score and plan
        if (q_score > q) {
            q = q_score;
            q_max = quiet.chain.score;
            plan = quiet.plan;
        }
    });

    if (q > INT32_MIN) {
        eval += q;
    }

    // Static evaluation value
    eval += eval::get_static(field, w);

    u8 heights[6];
    field.get_heights(heights);

    // Avoids wasting space on the 14th row
    i32 waste_14 = eval::get_waste_14(field.row14);
    eval += waste_14 * w.waste_14;

    // Avoids garbage puyo
    eval += field.data[static_cast<u8>(cell::Type::GARBAGE)].get_count() * w.nuisance;

    // Field side bias
    i32 height_left = heights[0] + heights[1];
    i32 height_right = heights[3] + heights[4] + heights[5];
    eval += (std::max(height_left, height_right) - i32(heights[2])) * w.side;

    // Avoids tearing
    eval += tear * w.tear;

    // Avoids wasting resource by popping puyos
    eval += waste * w.waste;

    return Result {
        .value = eval,
        .q = q_max,
        .plan = plan
    };
};

// Returns static eval
i32 get_static(Field& field, const Weight& w)
{
    i32 eval = 0;

    u8 heights[6];
    field.get_heights(heights);

    // Field's shape
    const i32 shape_coef[6] = { 2, 2, 2, -2, -2, -2 };
    eval += eval::get_shape(heights, shape_coef) * w.shape;

    // Field's u shape
    i32 u = eval::get_u(heights);
    eval += u * w.u;

    // Avoids wells
    i32 well = eval::get_well(heights);
    eval += well * w.well;

    // Avoids bumps
    i32 bump = eval::get_bump(heights);
    eval += bump * w.bump;

    // Puyo connections
    auto [link_2, link_3] = eval::get_link_23(field);
    eval += link_2 * w.link_2;
    eval += link_3 * w.link_3;

    return eval;
};

// Returns how close the field's shape is to the ideal shape
i32 get_shape(u8 heights[6], const i32 coef[6])
{
    i32 shape = 0;

    i32 height_avg = 0;

    for (i32 i = 0; i < 6; ++i) {
        height_avg += heights[i];
    }

    height_avg = height_avg / 6;

    for (i32 i = 0; i < 6; ++i) {
        shape += std::abs(i32(heights[i]) - height_avg - coef[i]);
    }

    return shape;
};

// Evaluates the field's u shape
// A field's shape is considered to be an u shape when the columns in the middle are lower than the columns on the outside
i32 get_u(u8 heights[6])
{
    i32 u = 0;

    u += std::max(0, i32(heights[2]) - i32(heights[1]));
    u += std::max(0, i32(heights[2]) - i32(heights[0]));
    u += std::max(0, i32(heights[1]) - i32(heights[0]));

    // u += std::max(0, i32(heights[3]) - i32(heights[4]));
    // u += std::max(0, i32(heights[3]) - i32(heights[5]));
    // u += std::max(0, i32(heights[4]) - i32(heights[5]));

    return u;
};

};

};
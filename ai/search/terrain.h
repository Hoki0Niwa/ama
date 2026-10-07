#pragma once

#include "../../core/core.h"

// Measures of a field's surface and connections that both evaluations use: the dfs one that
// decides attacks and the beam one that builds chains. One copy, read under either namespace.
namespace terrain
{

// Returns how extendable the trigger point is
inline i32 get_chi(u8 heights[6], i8 x)
{
    i32 chi = 0;

    if (x < 5) {
        for (auto i = x + 1; i < 6; ++i) {
            if (heights[i] > heights[x]) {
                break;
            }

            chi += 1;
        }

        for (auto i = x + 1; i < 6; ++i) {
            if (heights[i] >= heights[x]) {
                break;
            }

            chi += 1;
        }
    }

    if (x > 0) {
        for (auto i = x - 1; i >= 0; --i) {
            if (heights[i] > heights[x]) {
                break;
            }

            chi += 1;
        }

        for (auto i = x - 1; i >= 0; --i) {
            if (heights[i] >= heights[x]) {
                break;
            }

            chi += 1;
        }
    }

    return chi;
};

// Returns the field's well depth
// If a column is lower than its 2 nearby columns, we consider that a well
inline i32 get_well(u8 heights[6])
{
    i32 well = 0;

    if (heights[0] < heights[1]) {
        well += heights[1] - heights[0];
    }

    if (heights[5] < heights[4]) {
        well += heights[4] - heights[5];
    }

    for (i32 i = 1; i < 5; ++i) {
        if (heights[i] < heights[i - 1] && heights[i] < heights[i + 1]) {
            well += std::min(heights[i - 1], heights[i + 1]) - heights[i];
        }
    }

    return well;
};

// Evaluates the field's bumpiness
// If a column is higher than its 2 nearby columns, it's considered a bump
inline i32 get_bump(u8 heights[6])
{
    i32 bump = 0;

    for (i32 i = 1; i < 5; ++i) {
        if (heights[i] > heights[i - 1] && heights[i] > heights[i + 1]) {
            bump += heights[i] - std::max(heights[i - 1], heights[i + 1]);
        }
    }

    return bump;
};

// Returns the number connections in the field
inline i32 get_link(Field& field)
{
    i32 link = 0;

    for (u8 p = 0; p < cell::COUNT - 1; ++p) {
        __m128i m12 = field.data[p].get_mask_12().data;

        FieldBit hor;
        hor.data = _mm_slli_si128(m12, 2) & m12;
        link += hor.get_count();

        FieldBit ver;
        ver.data = _mm_slli_epi16(m12, 1) & m12;
        link += ver.get_count();
    }

    return link;
};

// Returns the number of 2-connected and 3-connected links in the field
inline std::pair<i32, i32> get_link_23(Field& field)
{
    i32 link_2 = 0;
    i32 link_3 = 0;

    for (u8 p = 0; p < cell::COUNT - 1; ++p) {
        __m128i m12 = field.data[p].get_mask_12().data;

        __m128i r = _mm_srli_si128(m12, 2) & m12;
        __m128i l = _mm_slli_si128(m12, 2) & m12;
        __m128i u = _mm_srli_epi16(m12, 1) & m12;
        __m128i d = _mm_slli_epi16(m12, 1) & m12;

        __m128i ud_and = u & d;
        __m128i lr_and = l & r;
        __m128i ud_or = u | d;
        __m128i lr_or = l | r;

        FieldBit l3;
        FieldBit l2;

        l3.data = (ud_or & lr_or) | ud_and | lr_and;
        l2.data = _mm_andnot_si128(l3.get_expand().data, u | l);

        link_2 += l2.get_count();
        link_3 += l3.get_count();
    }

    return { link_2, link_3 };
};

// Returns the remaining reachable cells left on the 14th row
inline i32 get_waste_14(u8 row14)
{
    i32 space = 1;

    for (i32 i = 3; i < 6; ++i) {
        if ((row14 >> i) & 1) {
            break;
        }

        space += 1;
    }

    for (i32 i = 1; i >= 0; --i) {
        if ((row14 >> i) & 1) {
            break;
        }

        space += 1;
    }

    return 6 - space;
};

};

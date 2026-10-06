#pragma once

#include "../core/core.h"

// Offset stock: how many chain links a board can pop, one small trigger after another, without a
// placement that pops nothing in between. Under the Fever rule every link that offsets nuisance
// earns one gauge step whatever it scores, so this counts links and ignores points.
namespace fever
{

namespace stock
{

struct Result
{
    i32 units = 0;  // Links weighted by how few puyos fire them, up to the links wanted
    i32 links = 0;  // The same links, unweighted
    i32 colors = 0; // Colors that fire something with a single puyo
    i32 longest = 0; // The longest chain any one trigger of the board fires
};

// A link fired by 1, 2 or 3 puyos of its color counts 4, 2 or 1 units: one puyo comes with any piece
// that has the color, three hardly ever come together.
constexpr i32 UNITS[4] = { 0, 4, 2, 1 };

// Triggers taken one after another, each from the board the last one left
constexpr i32 ROUNDS = 4;

inline Result evaluate(Field field, i32 want)
{
    Result result;

    for (i32 round = 0; round < ROUNDS && result.links < want; ++round) {
        u8 heights[6];
        field.get_heights(heights);

        i32 best_need = 4;
        i32 best_links = 0;
        Field best_remain;
        bool ready[cell::COUNT - 1] = { false };

        for (i8 x = 0; x < 6; ++x) {
            // The 12th row is the highest a dropped puyo stays on
            i32 drop_max = std::min(3, 12 - i32(heights[x]));

            for (u8 p = 0; p < cell::COUNT - 1; ++p) {
                auto plan = field;

                for (i32 need = 1; need <= drop_max; ++need) {
                    plan.data[p].set_bit(x, heights[x] + need - 1);

                    if (plan.data[p].get_mask_group_4(x, heights[x]).get_count() < 4) {
                        continue;
                    }

                    ready[p] = ready[p] || need == 1;

                    // The fewest puyos first; among those the longer chain
                    if (need <= best_need || round == 0) {
                        auto remain = plan;
                        i32 links = remain.pop_count();

                        if (round == 0) {
                            result.longest = std::max(result.longest, links);
                        }

                        if (need < best_need || (need == best_need && links > best_links)) {
                            best_need = need;
                            best_links = links;
                            best_remain = remain;
                        }
                    }

                    break;
                }
            }
        }

        if (round == 0) {
            for (bool r : ready) {
                result.colors += r;
            }
        }

        if (best_links <= 0) {
            break;
        }

        i32 taken = std::min(best_links, want - result.links);

        result.links += taken;
        result.units += taken * UNITS[best_need];
        field = best_remain;
    }

    return result;
};

};

};

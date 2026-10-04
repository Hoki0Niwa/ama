#include "quiet.h"

namespace beam
{

namespace quiet
{

namespace
{

void generate_with_heights(Field& field, const u8 heights[6], i8 x_min, i8 x_max,
                           i32 drop, const std::function<void(i8, i8, i8)>& callback);

// Searches the same chain extensions, optionally retaining their point score.
void search_impl(
    Field& field,
    i32 drop,
    const std::function<void(Result)>& callback,
    bool score
)
{
    u8 heights[6];
    field.get_heights(heights);

    auto [x_min, x_max] = quiet::get_bound(heights);

    // Drops puyo until a chain is triggered for all columns and colors
    generate_with_heights(
        field,
        heights,
        x_min,
        x_max,
        drop,
        [&] (i8 x, i8 p, i8 need) {
            // Drops puyo
            auto plan = field;

            for (i32 i = 0; i < need; ++i) {
                plan.data[p].set_bit(x, heights[x] + i);
            }

            // Pops field
            chain::Score chain;
            if (score) {
                auto pop = plan.pop();
                chain.count = pop.get_size();
                if (chain.count > 1) chain = chain::get_score(pop);
            }
            else {
                chain.count = plan.pop_count();
            }

            // Checks for callback
            if (chain.count > 1) {

                callback(Result {
                    .chain = chain::Score {
                        .count = chain.count,
                        .score = chain.score
                    },
                    .x = x,
                    .key = need,
                    .remain = plan
                });
            }
        }
    );
};

// Finds dropping positions that may trigger a chain
void generate_with_heights(
    Field& field,
    const u8 heights[6],
    i8 x_min,
    i8 x_max,
    i32 drop,
    const std::function<void(i8, i8, i8)>& callback
)
{
    for (i8 x = x_min; x <= x_max; ++x) {
        // Finds the maximum amount of puyo blobs that can be drop
        i32 drop_max = std::min(drop, 12 - i32(heights[x]));

        if (drop_max <= 0) {
            continue;
        }

        // For every color
        for (u8 p = 0; p < cell::COUNT - 1; ++p) {
            auto copy = field;

            // Continues dropping puyo blobs until we trigger a chain
            for (i8 i = 0; i < drop_max; ++i) {
                copy.data[p].set_bit(x, heights[x] + i);

                if (copy.data[p].get_mask_group_4(x, heights[x]).get_count() >= 4) {
                    callback(x, p, i + 1);
                    break;
                }
            }
        }
    }
};

}

void search(Field& field, i32 drop, std::function<void(Result)> callback)
{
    search_impl(field, drop, callback, true);
};

void search_count(Field& field, i32 drop, std::function<void(Result)> callback)
{
    search_impl(field, drop, callback, false);
};

void generate(Field& field, i8 x_min, i8 x_max, i32 drop,
              std::function<void(i8, i8, i8)> callback)
{
    u8 heights[6];
    field.get_heights(heights);
    generate_with_heights(field, heights, x_min, x_max, drop, callback);
};

// Gets the dropping bound
std::pair<i8, i8> get_bound(u8 heights[6])
{
    i8 x_min = 2;
    i8 x_max = 2;

    for (i8 x = 3; x < 6; ++x) {
        if (heights[x] > 11) {
            break;
        }

        x_max += 1;
    }

    for (i8 x = 1; x > -1; --x) {
        if (heights[x] > 11) {
            break;
        }

        x_min -= 1;
    }

    return { x_min, x_max };
};

};

};
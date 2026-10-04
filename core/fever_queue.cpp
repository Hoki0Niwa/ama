#include "fever_queue.h"

namespace fever
{

std::optional<Queue> create_queue(const dropset::Character& character, u64 seed, usize count, u64 start)
{
    Queue result;
    result.reserve(count);

    Rng rng{ seed };

    for (usize i = 0; i < count; ++i) {
        const auto drop = dropset::drop_at(character, start + i);
        if (!drop) return std::nullopt;

        const auto a = rng.color();
        auto b = cell::Type::NONE;
        if (*drop == dropset::Drop::QUAD) b = rng.color_except(a);
        else if (*drop != dropset::Drop::BIG) b = rng.color();

        const auto value = make_piece(*drop, a, b);
        if (!value) return std::nullopt;
        result.push_back(*value);
    }

    return result;
}

std::optional<Queue> create_queue(std::string_view id, u64 seed, usize count, u64 start)
{
    const auto* character = dropset::find(id);
    return character ? create_queue(*character, seed, count, start) : std::nullopt;
}

std::optional<Queue> create_queue_virtual(const dropset::Character& character, i32 id, usize count, u64 start)
{
    // Same bags as beam::get_queue_random
    constexpr u8 bag[VIRTUAL_COUNT][4] = {
        { 0, 1, 2, 3 },
        { 0, 2, 1, 3 },
        { 0, 3, 1, 2 },
        { 1, 2, 0, 3 },
        { 1, 3, 0, 2 },
        { 2, 3, 0, 1 }
    };

    if (id < 0 || id >= VIRTUAL_COUNT) return std::nullopt;

    Queue result;
    result.reserve(count);

    usize dealt = 0;
    auto deal = [&] () { return cell::Type(bag[id][dealt++ % 4]); };

    for (usize i = 0; i < count; ++i) {
        const auto drop = dropset::drop_at(character, start + i);
        if (!drop) return std::nullopt;

        // BIG's color is chosen on placement, so it takes nothing from the bag.
        // Consecutive bag colors differ, which satisfies QUAD's constraint.
        const auto a = *drop == dropset::Drop::BIG ? cell::Type::RED : deal();
        const auto b = *drop == dropset::Drop::BIG ? cell::Type::NONE : deal();

        const auto value = make_piece(*drop, a, b);
        if (!value) return std::nullopt;
        result.push_back(*value);
    }

    return result;
}

}

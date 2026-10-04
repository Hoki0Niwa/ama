#pragma once

#include "dropset.h"

namespace fever
{

using Queue = std::vector<piece::Piece>;

// Number of deterministic color bags used for the search's virtual queues.
constexpr i32 VIRTUAL_COUNT = 6;

// Prototype color model: splitmix64, one draw per color, 4 independent uniform
// colors. This does NOT reproduce the Steam version's color generation.
struct Rng
{
    u64 state;

    constexpr u64 next()
    {
        state += 0x9E3779B97F4A7C15ull;
        u64 z = state;
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
        return z ^ (z >> 31);
    }

    constexpr cell::Type color() { return cell::Type(next() >> 62); }

    // Uniform over the three colors other than the given one.
    constexpr cell::Type color_except(cell::Type other)
    {
        return cell::Type((u64(other) + 1 + (((next() >> 32) * 3) >> 32)) % 4);
    }
};

// TRIPLE_VERTICAL is (A, A, B), TRIPLE_HORIZONTAL is (A, B, A); B may equal A.
// QUAD starts as left column A, right column B with A != B. BIG keeps only A.
// TRIPLE_UNKNOWN is never guessed.
constexpr std::optional<piece::Piece> make_piece(dropset::Drop drop, cell::Type a, cell::Type b)
{
    using piece::Shape;
    constexpr auto N = cell::Type::NONE;
    if (!piece::is_color(a)) return std::nullopt;
    if (drop == dropset::Drop::BIG) return piece::Piece{ Shape::BIG, { a, N, N, N } };
    if (!piece::is_color(b)) return std::nullopt;
    switch (drop) {
    case dropset::Drop::PAIR: return piece::Piece{ Shape::PAIR, { a, b, N, N } };
    case dropset::Drop::TRIPLE_VERTICAL: return piece::Piece{ Shape::TRIPLE, { a, a, b, N } };
    case dropset::Drop::TRIPLE_HORIZONTAL: return piece::Piece{ Shape::TRIPLE, { a, b, a, N } };
    case dropset::Drop::QUAD:
        if (a == b) return std::nullopt;
        return piece::Piece{ Shape::QUAD, { a, a, b, b } };
    default: return std::nullopt;
    }
}

// The pieces for moves [start, start + count) of the character's cycle. The
// same character, seed, start and count always give the same queue.
std::optional<Queue> create_queue(const dropset::Character& character, u64 seed, usize count, u64 start = 0);
std::optional<Queue> create_queue(std::string_view id, u64 seed, usize count, u64 start = 0);

// Virtual future for the search: shapes from the cycle, colors dealt in order
// from one of the VIRTUAL_COUNT fixed bags. Uses no random state.
std::optional<Queue> create_queue_virtual(const dropset::Character& character, i32 id, usize count, u64 start);

}

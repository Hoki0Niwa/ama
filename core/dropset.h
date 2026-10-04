#pragma once

#include "piece.h"
#include <span>
#include <string_view>

namespace dropset
{

constexpr usize PERIOD = 16;

enum class Status : u8 { OFFICIAL, PLAYER, COUNTS_ONLY, UNKNOWN };
enum class Drop : u8 { PAIR, TRIPLE_VERTICAL, TRIPLE_HORIZONTAL, TRIPLE_UNKNOWN, QUAD, BIG };

struct Character
{
    std::string_view id;
    std::string_view pattern;     // Empty when the cycle itself is unknown.
    std::string_view pattern_alt; // Legacy notation; empty when unavailable.
    Status status;
};

// L/J mapping is centralized here. Confirmed against the official Amitie and
// Raffina diagrams and the published character-selection screenshots.
constexpr std::optional<Drop> decode(char symbol)
{
    switch (symbol) {
    case '2': return Drop::PAIR;
    case 'L': return Drop::TRIPLE_VERTICAL;
    case 'J': return Drop::TRIPLE_HORIZONTAL;
    case '3': return Drop::TRIPLE_UNKNOWN;
    case '4': return Drop::QUAD;
    case '0': case '*': return Drop::BIG;
    }
    return std::nullopt;
}

constexpr piece::Shape shape_of(Drop drop)
{
    switch (drop) {
    case Drop::PAIR: return piece::Shape::PAIR;
    case Drop::TRIPLE_VERTICAL: case Drop::TRIPLE_HORIZONTAL: case Drop::TRIPLE_UNKNOWN:
        return piece::Shape::TRIPLE;
    case Drop::QUAD: return piece::Shape::QUAD;
    case Drop::BIG: return piece::Shape::BIG;
    }
    return piece::Shape::PAIR;
}

constexpr std::string_view status_name(Status status)
{
    switch (status) {
    case Status::OFFICIAL: return "official";
    case Status::PLAYER: return "player";
    case Status::COUNTS_ONLY: return "counts_only";
    case Status::UNKNOWN: return "unknown";
    }
    return "unknown";
}

std::span<const Character> characters();
const Character* find(std::string_view id);

// Indices are zero-based and wrap at 16. No fallback character or guessed shape.
std::optional<Drop> drop_at(const Character& character, u64 index);
std::optional<Drop> drop_at(std::string_view id, u64 index);
std::optional<piece::Shape> shape_at(std::string_view id, u64 index);

}

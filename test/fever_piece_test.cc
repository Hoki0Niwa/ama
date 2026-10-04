#include "../core/dropset.h"
#include <stdexcept>

namespace
{
void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

char symbol(dropset::Drop drop)
{
    switch (drop) {
    case dropset::Drop::PAIR: return '2';
    case dropset::Drop::TRIPLE_VERTICAL: return 'L';
    case dropset::Drop::TRIPLE_HORIZONTAL: return 'J';
    case dropset::Drop::TRIPLE_UNKNOWN: return '3';
    case dropset::Drop::QUAD: return '4';
    case dropset::Drop::BIG: return '0';
    }
    throw std::runtime_error("invalid drop");
}
}

int main()
{
    using namespace piece;
    using cell::Type;
    constexpr auto R = Type::RED, Y = Type::YELLOW, G = Type::GREEN, B = Type::BLUE, N = Type::NONE;
    static_assert(to_pair(from_pair({ R, B })).value() == cell::Pair{ R, B });
    for (u8 a = 0; a < 6; ++a) for (u8 b = 0; b < 6; ++b) {
        const cell::Pair pair{ Type(a), Type(b) };
        const auto value = from_pair(pair);
        require(value.colors[0] == pair.first && value.colors[1] == pair.second, "pair order changed");
        require(cell_count(value.shape) == 2, "pair size");
        const bool valid = a < 4 && b < 4;
        require(is_valid(value) == valid && to_pair(value).has_value() == valid, "pair validation");
        if (valid) require(*to_pair(value) == pair, "pair round trip");
    }
    for (u8 a = 0; a < 4; ++a) for (u8 b = 0; b < 4; ++b) for (u8 c = 0; c < 4; ++c) {
        const Piece triple{ Shape::TRIPLE, { Type(a), Type(b), Type(c), N } };
        require(is_valid(triple) == (a == b || a == c), "triple color placement");
        require(!to_pair(triple), "triple became pair");
    }
    for (u8 a = 0; a < 4; ++a) for (u8 b = 0; b < 4; ++b)
    for (u8 c = 0; c < 4; ++c) for (u8 d = 0; d < 4; ++d) {
        const Piece quad{ Shape::QUAD, { Type(a), Type(b), Type(c), Type(d) } };
        // Independent check: two colors occurring twice and not checkerboard.
        std::array<int, 4> counts{};
        for (auto color : quad.colors) ++counts[usize(color)];
        const auto twos = std::count(counts.begin(), counts.end(), 2);
        require(is_valid(quad) == (twos == 2 && !(a == d && b == c)), "quad constraints");
        require(!to_pair(quad), "quad became pair");
    }
    for (u8 c = 0; c < 6; ++c) {
        const Piece big{ Shape::BIG, { Type(c), N, N, N } };
        require(is_valid(big) == (c < 4), "big color validation");
        require(cell_count(big.shape) == 4 && color_count(big.shape) == 1, "big representation");
        require(!to_pair(big), "big became pair");
    }
    require(!is_valid({ Shape::PAIR, { R, B, G, N } }), "unused colors accepted");
    require(!is_valid({ Shape::TRIPLE, { R, Y, G, B } }), "triple padding accepted");
    require(!is_valid({ Shape(255), { N, N, N, N } }), "invalid shape accepted");
    require(!is_valid(Piece{}), "default piece accepted");

    using namespace dropset;
    require(!find("unknown-id") && !shape_at("unknown-id", 0), "unknown id fallback");
    require(!drop_at("Raffina", 0), "case-sensitive id changed");
    require(!decode('X'), "invalid symbol accepted");
    const Character unknown{ "unknown", "2222222222222222", "", Status::UNKNOWN };
    require(!drop_at(unknown, 0), "unknown status guessed");
    const Character malformed{ "bad", "22", "", Status::PLAYER };
    require(!drop_at(malformed, 0), "short cycle accepted");
    const Character legacy{ "legacy", "", "22322*2223223224", Status::PLAYER };
    require(drop_at(legacy, 2) == Drop::TRIPLE_UNKNOWN, "legacy triple guessed");
    require(shape_of(*drop_at(legacy, 2)) == Shape::TRIPLE, "legacy triple shape");
    require(drop_at(legacy, 5) == Drop::BIG, "legacy big");
    require(drop_at("raffina", 2) == Drop::TRIPLE_VERTICAL, "Raffina third");
    require(drop_at("raffina", 9) == Drop::TRIPLE_HORIZONTAL, "Raffina tenth");
    require(drop_at("raffina", 12) == Drop::TRIPLE_VERTICAL, "Raffina thirteenth");
    require(drop_at("draco", 11) == Drop::TRIPLE_HORIZONTAL, "Draco correction");
    require(drop_at("risukuma", 1) == Drop::TRIPLE_HORIZONTAL, "Risukuma second");
    require(characters().size() == 26, "character count");
    for (const auto& character : characters()) {
        require(find(character.id) == &character, "lookup table identity");
        std::cout << character.id << '\t' << status_name(character.status) << '\t'
                  << character.pattern << '\t' << character.pattern_alt << '\t';
        for (u64 index = 0; index < 48; ++index) {
            const auto drop = drop_at(character, index);
            std::cout << (drop ? symbol(*drop) : '?');
            const auto shape = shape_at(character.id, index);
            require(drop.has_value() == shape.has_value(), "shape availability");
            if (drop) require(*shape == shape_of(*drop), "shape mismatch");
        }
        const auto last = drop_at(character, std::numeric_limits<u64>::max());
        require(last == drop_at(character, 15), "large index wrapping");
        std::cout << '\t' << (last ? symbol(*last) : '?') << '\n';
    }
    std::cerr << "Piece and dropset checks passed\n";
}

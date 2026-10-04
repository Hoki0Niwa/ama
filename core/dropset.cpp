#include "dropset.h"

namespace dropset
{
namespace
{
// Keep in sync with data/fever/dropsets.json; test/test_fever_piece.py compares
// the compiled table, its provenance and every slot of repeated cycles.
constexpr Character TABLE[] = {
    { "arle", "2222222222222222", "2222222222222222", Status::OFFICIAL },
    { "amitie", "222L2220222J2224", "2223222*22232224", Status::PLAYER },
    { "ringo", "222L0222J0422L2L", "", Status::PLAYER },
    { "hed", "22L22J202L22J220", "2232232*2322322*", Status::PLAYER },
    { "sultana", "L202J24202L242J2", "", Status::PLAYER },
    { "schezo", "2222L242J202L242", "", Status::PLAYER },
    { "sig", "222L222422J20224", "222322242232*224", Status::PLAYER },
    { "maguro", "22L22J2242202224", "", Status::PLAYER },
    { "ciel", "22L2J202L202J224", "", Status::PLAYER },
    { "penglai", "222L22022J220224", "222322*22322*224", Status::PLAYER },
    { "rulue", "2224222022242220", "2224222*2224222*", Status::PLAYER },
    { "raffina", "22L220222J22L224", "22322*2223223224", Status::OFFICIAL },
    { "suketoudara", "22L22J202L22J220", "2232232*2322322*", Status::PLAYER },
    { "ally", "2222L22220222224", "", Status::PLAYER },
    { "ragnus", "2222L242J202L242", "", Status::PLAYER },
    { "risukuma", "2J22220222422L22", "", Status::PLAYER },
    { "draco", "2222222222LJ0JL4", "222222222233*334", Status::PLAYER },
    { "witch", "JL22J22242220222", "", Status::PLAYER },
    { "harpy", "2L202J202L242224", "", Status::PLAYER },
    { "serilly", "222L22J022L022J4", "", Status::PLAYER },
    { "carbuncle", "2L024J202L420J24", "", Status::PLAYER },
    { "satan", "222L222022242220", "", Status::PLAYER },
    { "hartmann", "2L202J222L24202J", "", Status::PLAYER },
    { "alex", "2L2J2L202J2L2J24", "2323232*23232324", Status::PLAYER },
    { "rafisol", "222L222J24L024J0", "", Status::PLAYER },
    { "paprisu", "2L22J22L420J2024", "", Status::PLAYER },
};
static_assert(std::size(TABLE) == 26);
static_assert([] {
    for (const auto& character : TABLE) {
        if (character.status == Status::UNKNOWN) {
            if (!character.pattern.empty() || !character.pattern_alt.empty()) return false;
            continue;
        }
        const auto pattern = character.pattern.empty() ? character.pattern_alt : character.pattern;
        if (pattern.size() != PERIOD) return false;
        for (char symbol : pattern) if (!decode(symbol)) return false;
    }
    return true;
}());
}

std::span<const Character> characters() { return TABLE; }

const Character* find(std::string_view id)
{
    for (const auto& character : TABLE) if (character.id == id) return &character;
    return nullptr;
}

std::optional<Drop> drop_at(const Character& character, u64 index)
{
    if (character.status == Status::UNKNOWN) return std::nullopt;
    const auto pattern = character.pattern.empty() ? character.pattern_alt : character.pattern;
    if (pattern.size() != PERIOD) return std::nullopt;
    return decode(pattern[index % PERIOD]);
}

std::optional<Drop> drop_at(std::string_view id, u64 index)
{
    const auto* character = find(id);
    return character ? drop_at(*character, index) : std::nullopt;
}

std::optional<piece::Shape> shape_at(std::string_view id, u64 index)
{
    const auto drop = drop_at(id, index);
    return drop ? std::optional{ shape_of(*drop) } : std::nullopt;
}

}

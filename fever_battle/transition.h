#pragma once
#include "../core/core.h"
#include "../lib/nlohmann/json.hpp"
#include "rate_schedule.h"
#include <algorithm>
#include <bit>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

// What every battle search does to a board between two placements: reading a
// bounded integer, scoring a link, dropping nuisance on known or unknown
// columns, and taking in the opponent's observed chain. One copy, so the
// searches cannot disagree about the rules.
namespace fever_battle {

inline int number(const nlohmann::json& j, const char* key, i64 low, i64 high) {
    const auto& v = j.at(key);
    if (!v.is_number_integer() || v < low || v > high)
        throw std::invalid_argument(std::string(key) + " out of range");
    return v.get<int>();
}

// The player's documented Fever order of the columns that take a partial row.
// The next remainder resumes after the last nuisance puyo actually dropped.
constexpr int GARBAGE_ORDER[] = {0, 3, 2, 5, 1, 4};

// Drops `count` nuisance from a known position of the column order. Returns
// how many found their column full (above row 13 they vanish).
inline int drop_nuisance(Field& field, int count, int phase) {
    u8 heights[6]; field.get_heights(heights);
    int amounts[6]; for (auto& n : amounts) n = count / 6;
    for (int i = 0; i < count % 6; ++i) ++amounts[GARBAGE_ORDER[(phase + i) % 6]];
    int discarded = 0;
    for (int x = 0; x < 6; ++x) for (int i = 0; i < amounts[x]; ++i) {
        if (heights[x] >= 13) ++discarded;
        else field.set_cell(x, heights[x]++, cell::Type::GARBAGE);
    }
    return discarded;
}

// Calls visit(board) for every choice of the columns that take the partial
// row, when the position in the column order is not known. Nuisance that finds
// its column full vanishes above row 13, as a piece placed there does: a full
// side column is no loss, and only the board's own death test decides.
template <class Visit>
void each_remainder_drop(const Field& source, int count, Visit visit) {
    const int whole = count / 6, extra = count % 6;
    for (unsigned mask = 0; mask < 64; ++mask) {
        if (std::popcount(mask) != extra) continue;
        auto board = source;
        u8 heights[6]; board.get_heights(heights);
        for (int x = 0; x < 6; ++x) {
            const int amount = whole + ((mask >> x) & 1);
            for (int i = 0; i < amount && heights[x] < 13; ++i)
                board.set_cell(x, heights[x]++, cell::Type::GARBAGE);
        }
        visit(board);
    }
}

struct Bonuses {
    std::vector<int> group, color;
    int minimum = 0, maximum = 0;
    Bonuses() = default;
    explicit Bonuses(const nlohmann::json& j):
        group(j.at("group").get<std::vector<int>>()), color(j.at("color").get<std::vector<int>>()),
        minimum(j.at("multiplier_min").get<int>()), maximum(j.at("multiplier_max").get<int>()) {}
};

struct Link {
    std::vector<int> groups;    // size of every group popped, colour by colour
    int colors = 0, cells = 0;
    i64 points = 0;
};

// One link of a chain: `mask` holds the puyos it pops, `power` its chain power.
inline Link score_link(Field mask, int power, const Bonuses& bonuses) {
    Link link; int group_bonus = 0;
    for (int c = 0; c < cell::COUNT - 1; ++c) {
        if (mask.data[c].is_empty()) continue;
        ++link.colors;
        while (!mask.data[c].is_empty()) {
            auto group = mask.data[c].get_mask_group_lsb();
            const int n = group.get_count();
            link.cells += n; link.groups.push_back(n);
            group_bonus += bonuses.group.at(std::min(11, n));
            mask.data[c] = mask.data[c] & ~group;
        }
    }
    const int multiplier = std::clamp(power + group_bonus + bonuses.color.at(link.colors),
        bonuses.minimum, bonuses.maximum);
    link.points = 10 * link.cells * multiplier;
    return link;
}

// Takes in the opponent's observed chain up to frame `until`. A link's points
// first offset what we have sent them; the rest flies to us, and is confirmed
// when their chain ends. Offsetting now cannot erase a link not yet scored.
template <class Index, class Own>
void advance_enemy(const nlohmann::json& events, const RateSchedule& rates, int until, Index& index,
                   Own& fixed, Own& flying, i64& enemy_fixed, i64& enemy_flying, i64& enemy_remainder) {
    while (index < Index(events.size()) && events[index]["frame"].template get<int>() <= until) {
        const auto& event = events[index++];
        if (event["type"] == "end") { fixed += flying; flying = 0; continue; }
        i64 total = event["points"].template get<i64>() + enemy_remainder;
        const int rate = rates.at(event["frame"].template get<int>(), true);
        i64 amount = total / rate; enemy_remainder = total % rate;
        if (enemy_fixed + enemy_flying && amount == 0) amount = 1;
        auto n = std::min(enemy_fixed, amount); enemy_fixed -= n; amount -= n;
        n = std::min(enemy_flying, amount); enemy_flying -= n; amount -= n;
        flying += Own(amount);
    }
}

// What the opponent has against nuisance sent to them, as their normal board
// stands: `hold` is what their own longest chain offsets, `kill` what fills the
// board once it lands (0: no such board, as in Fever or with a chain running),
// `links` the links they can pop one trigger after another, and `need` the
// offsets that take their gauge into Fever, where nothing falls.
struct Defense {
    // Pieces it takes them to make one more link to offset with (an estimate, not measured).
    static constexpr int PIECES_PER_LINK = 3;
    i64 hold = 0, kill = 0;
    int links = 0, need = 1;
    Defense() = default;
    explicit Defense(const nlohmann::json& j):
        hold(number(j, "hold", 0, 1000000000)), kill(number(j, "kill", 0, 1000000000)),
        links(number(j, "links", 0, 100)), need(number(j, "need", 0, 7)) {}
    // The share of a kill that `pending` nuisance on them comes to, when the
    // chain that sends it ends `frames` from now: what lands is what their
    // chain does not offset; they escape by filling the gauge, with the links
    // they have and one more for every PIECES_PER_LINK pieces they place until then.
    double kills(i64 pending, int frames, int piece_frames) const {
        if (kill <= 0) return 0.0;
        const double landed = std::clamp(double(pending - hold) / double(kill), 0.0, 1.0);
        const double escape = need <= 0 ? 1.0 : std::clamp(
            (double(links) + double(frames) / double(PIECES_PER_LINK * std::max(1, piece_frames))) / double(need), 0.0, 1.0);
        // Half of what fills the board is far less than half a kill: the share is squared.
        return landed * landed * (1.0 - escape);
    }
};

// Identity of a search state for merging: the board's cells and the numbers given.
template <class... Numbers>
std::string state_key(const Field& field, Numbers... numbers) {
    std::string key(sizeof(Field), '\0');
    std::memcpy(key.data(), &field, sizeof(Field));
    ((key += std::to_string(numbers), key += ','), ...);
    return key;
}

}

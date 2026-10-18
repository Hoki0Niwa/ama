#include "control_moves.h"
#include "control.h"
#include "text.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <string>

namespace fever::control_moves {
namespace {
// Game rows 1..14 (row 1 = the 14th row) for the controller; the board is settled, so its heights say it all.
std::vector<std::string> rows_of(Field& field) {
    u8 h[6]; field.get_heights(h);
    std::vector<std::string> rows(14, std::string(6, '.'));
    for (int g = 2; g <= 14; ++g) for (int x = 0; x < 6; ++x)
        if (14 - g < int(h[x])) rows[size_t(g - 1)][size_t(x)] = '#';
    return rows;
}
// Lock cells settled as drop_piece settles them (bottom first, cells at the 14th row and above discarded).
bool settle(Field board, const piece::Piece& piece, const std::vector<std::pair<int, int>>& cells, Field& after) {
    after = board; u8 h[6]; after.get_heights(h);
    std::vector<int> order(cells.size());
    for (size_t k = 0; k < order.size(); ++k) order[k] = int(k);
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) { return cells[size_t(a)].second > cells[size_t(b)].second; });
    for (int k : order) {
        const int x = cells[size_t(k)].first - 1;
        if (x < 0 || x > 5) return false;
        if (h[x] >= 13) continue;
        after.set_cell(i8(x), i8(h[x]++), piece.colors[size_t(k)]);
    }
    return true;
}
struct Found { u32 mask = 0; std::array<std::vector<u8>, 24> programs{}; };
Found explore(Field field, const piece::Piece& piece, const rule::Rule& rules, int delay) {
    Found found;
    if (piece.shape != piece::Shape::TRIPLE) return found;
    control::Rules control_rules; control_rules.pad_seat = true;
    control::Carry carry; carry.pad.previous = 0;   // the buttons are released between pieces
    const auto routes = control::explore(rows_of(field), control::Shape::TRIPLE_L, carry, 600, control_rules,
                                         {1, 2, 1, 2}, delay);
    std::vector<Field> outcomes; std::vector<bool> usable;
    for (const auto& route : routes) { Field after; usable.push_back(settle(field, piece, route.cells, after)); outcomes.push_back(after); }
    for (int x = 0; x <= 4; ++x) for (int r = 0; r < 4; ++r) {
        auto target = field;
        if (!target.drop_piece(i8(x), direction::Type(r), piece, rules)) continue;
        int best = -1;
        for (size_t k = 0; k < routes.size(); ++k)
            if (usable[k] && outcomes[k] == target && (best < 0 || routes[k].program.size() < routes[size_t(best)].program.size()))
                best = int(k);
        if (best < 0) continue;
        found.mask |= u32(1) << (4 * x + r);
        const auto& program = routes[size_t(best)].program;
        found.programs[size_t(4 * x + r)].assign(program.begin() + std::min<size_t>(program.size(), size_t(std::max(0, delay))), program.end());
    }
    return found;
}
}

u32 triple_mask(Field field, const piece::Piece& piece, const rule::Rule& rules, int delay) {
    return explore(field, piece, rules, delay).mask;
}

std::optional<std::vector<u8>> triple_program(Field field, const piece::Piece& piece, const rule::Rule& rules,
                                              int x, int r, int delay) {
    if (x < 0 || x > 4 || r < 0 || r > 3) return {};
    auto found = explore(field, piece, rules, delay);
    if (!(found.mask >> (4 * x + r) & 1)) return {};
    return found.programs[size_t(4 * x + r)];
}
}

#ifdef AMA_FEVER_OPERATION
#ifdef _WIN32
#define AMA_CONTROL_EXPORT extern "C" __declspec(dllexport)
#else
#define AMA_CONTROL_EXPORT extern "C"
#endif
// For the bridge: the controller program for a triple, from the frame `delay` (see control_moves.h) until the
// lock, one control::Button byte per frame. heights: the six column heights of the settled board; piece: Ama's
// text ("L:BBR"); x/r: the placement in Ama's labels (the engine's reply, the bridge's `target`).
// Returns the number of frames, -1 when no program locks the goal, -2 for an invalid request, -3 when
// `capacity` is too small.
AMA_CONTROL_EXPORT int ama_operation_triple_program(const int* heights, const char* piece_text, int x, int r,
                                                    int delay, unsigned char* out, int capacity) {
    if (!heights || !piece_text || !out || capacity < 0 || delay < 0 || delay > 60 || x < 0 || x > 4 || r < 0 || r > 3)
        return -2;
    const auto piece = fever::text::to_piece(std::string(piece_text));
    if (!piece || piece->shape != piece::Shape::TRIPLE) return -2;
    Field field;
    for (int x = 0; x < 6; ++x) {
        if (heights[x] < 0 || heights[x] > 14) return -2;
        for (int y = 0; y < std::min(heights[x], 13); ++y) field.set_cell(i8(x), i8(y), cell::Type::GARBAGE);
    }
    const auto program = fever::control_moves::triple_program(field, *piece, rule::FEVER, x, r, delay);
    if (!program) return -1;
    if (int(program->size()) > capacity) return -3;
    std::memcpy(out, program->data(), program->size());
    return int(program->size());
}
#endif

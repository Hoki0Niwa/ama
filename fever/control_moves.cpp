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
// Down for two frames, up for one, as the bridge's measured programs. A press of one frame can come and go before
// the game reads the pad (2026-11-01: a turn lost so, and the piece dropped in its column; 22 of 6,326 taps on
// 2026-10-07). A turn and a shift may share the press.
constexpr u8 actions[] = {control::ROTATE_A, control::ROTATE_B, control::LEFT, control::RIGHT,
                          control::ROTATE_A | control::LEFT, control::ROTATE_A | control::RIGHT,
                          control::ROTATE_B | control::LEFT, control::ROTATE_B | control::RIGHT};
constexpr int max_presses = 12;
constexpr size_t max_nodes = 256;
struct Run { bool locked = false; control::State state{}; std::vector<std::pair<int, int>> cells; };
// Runs `program` and, when `finish`, holds DOWN until the lock. `locked` also when the program itself locks.
Run play(const control::Field& base, control::Field& scratch, control::Shape shape, const control::Rules& rules,
         const control::Carry& carry, int delay, const std::vector<u8>& program, bool finish, std::vector<u8>* tail = nullptr) {
    scratch.assign(base);
    control::Controller c(scratch, rules); c.restore(carry); c.spawn(shape, {1, 2, 1, 2});
    Run run;
    for (int k = 0; k < delay; ++k) if (c.step(0)) { run.locked = true; run.cells = c.cells(); return run; }
    for (u8 b : program) if (c.step(b)) { run.locked = true; run.cells = c.cells(); return run; }
    run.state = c.state();
    if (!finish) return run;
    for (int k = 0; k < 600; ++k) {
        if (tail) tail->push_back(control::DOWN);
        if (c.step(control::DOWN)) { run.locked = true; run.cells = c.cells(); return run; }
    }
    return run;
}
// Everything a short sequence of presses reaches, breadth first, each pose kept by its earliest (highest) visit.
// Not control::explore: its programs press for one frame, and miss the orders the tall boards need (a push off a
// wall, then a shift, then more turns). A goal counts only when its program also locks it started 1 and 3 frames
// later, for a bridge that sees the piece late.
template<class Visit> void widen(const control::Field& base, control::Shape shape, const control::Rules& rules,
                                 const control::Carry& carry, int delay, Visit&& visit) {
    control::Field scratch;
    std::vector<std::vector<u8>> queue{{}};
    std::vector<u32> seen;
    const auto key = [](const control::State& s, bool armed) {
        return u32(s.x) | u32(s.y & 0xff) << 4 | u32(s.rotation) << 12 | u32(std::min(s.touch, 3)) << 14 | u32(armed) << 16;
    };
    seen.push_back(key(play(base, scratch, shape, rules, carry, delay, {}, false).state, false));
    const auto settle_program = [&](const std::vector<u8>& program) {
        std::vector<u8> tail;
        const auto run = play(base, scratch, shape, rules, carry, delay, program, true, &tail);
        if (!run.locked) return;
        for (int late : {1, 3}) {
            const auto again = play(base, scratch, shape, rules, carry, delay + late, program, true);
            if (!again.locked || again.cells != run.cells) return;
        }
        auto whole = program; whole.insert(whole.end(), tail.begin(), tail.end());
        visit(whole, run.cells);
    };
    settle_program({});
    for (size_t head = 0; head < queue.size() && queue.size() < max_nodes; ++head) {
        if (queue[head].size() >= size_t(3 * max_presses)) continue;
        const auto before = play(base, scratch, shape, rules, carry, delay, queue[head], false);
        if (before.locked) continue;
        for (u8 action : actions) {
            auto program = queue[head]; program.insert(program.end(), {action, action, u8(0)});
            const auto after = play(base, scratch, shape, rules, carry, delay, program, false);
            if (after.locked) continue;
            // A turn that did not turn still counts towards a pair's quick turn: a second press is a new state.
            const bool unmoved = after.state.x == before.state.x && after.state.rotation == before.state.rotation;
            const u32 k = key(after.state, (action & (control::ROTATE_A | control::ROTATE_B)) && unmoved);
            if (std::find(seen.begin(), seen.end(), k) != seen.end()) continue;
            seen.push_back(k);
            settle_program(program);
            queue.push_back(std::move(program));
        }
    }
}
Found explore(Field field, const piece::Piece& piece, const rule::Rule& rules, int delay) {
    Found found;
    const bool pair = piece.shape == piece::Shape::PAIR;
    if (!pair && piece.shape != piece::Shape::TRIPLE) return found;
    const auto shape = pair ? control::Shape::PAIR : control::Shape::TRIPLE_L;
    control::Rules control_rules; control_rules.pad_seat = true;
    control::Carry carry; carry.pad.previous = 0;   // the buttons are released between pieces
    const auto rows = rows_of(field);
    struct Outcome { Field board; std::vector<u8> program; };
    std::vector<Outcome> outcomes;
    const auto add = [&](std::vector<u8> program, const std::vector<std::pair<int, int>>& cells) {
        Field after;
        if (!settle(field, piece, cells, after)) return;
        for (auto& known : outcomes) if (known.board == after) {
            if (program.size() < known.program.size()) known.program = std::move(program);
            return;
        }
        outcomes.push_back({after, std::move(program)});
    };
    const control::Field base(rows);
    widen(base, shape, control_rules, carry, delay, add);
    for (int x = 0; x <= (pair ? 5 : 4); ++x) for (int r = 0; r < 4; ++r) {
        auto target = field;
        if (!target.drop_piece(i8(x), direction::Type(r), piece, rules)) continue;
        for (auto& known : outcomes) if (known.board == target) {
            found.mask |= u32(1) << (4 * x + r);
            found.programs[size_t(4 * x + r)] = known.program;
            break;
        }
    }
    return found;
}
}

u32 triple_mask(Field field, const piece::Piece& piece, const rule::Rule& rules, int delay) {
    return explore(field, piece, rules, delay).mask;
}

std::optional<std::vector<u8>> triple_program(Field field, const piece::Piece& piece, const rule::Rule& rules,
                                              int x, int r, int delay) {
    if (x < 0 || x > (piece.shape == piece::Shape::PAIR ? 5 : 4) || r < 0 || r > 3) return {};
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
// `capacity` is too small. A pair ("2:RG") is asked for the same way.
AMA_CONTROL_EXPORT int ama_operation_triple_program(const int* heights, const char* piece_text, int x, int r,
                                                    int delay, unsigned char* out, int capacity) {
    if (!heights || !piece_text || !out || capacity < 0 || delay < 0 || delay > 60 || x < 0 || x > 5 || r < 0 || r > 3)
        return -2;
    const auto piece = fever::text::to_piece(std::string(piece_text));
    if (!piece || (piece->shape != piece::Shape::TRIPLE && piece->shape != piece::Shape::PAIR)) return -2;
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
// The placements (bit 4*x+r) the controller locks for a pair ("2:RG") or triple. For checks and measurement.
AMA_CONTROL_EXPORT long long ama_operation_control_mask(const int* heights, const char* piece_text, int delay) {
    if (!heights || !piece_text || delay < 0 || delay > 60) return -2;
    const auto piece = fever::text::to_piece(std::string(piece_text));
    if (!piece) return -2;
    Field field;
    for (int x = 0; x < 6; ++x) {
        if (heights[x] < 0 || heights[x] > 14) return -2;
        for (int y = 0; y < std::min(heights[x], 13); ++y) field.set_cell(i8(x), i8(y), cell::Type::GARBAGE);
    }
    return fever::control_moves::triple_mask(field, *piece, rule::FEVER, delay);
}
#endif

#pragma once
#include "../core/core.h"
#include <optional>
#include <vector>

// Triple placements through the game's own piece controller (fever/control.*, ported from the Steam build).
// The bridge's first press lands on control frame 1 at the earliest when it sees the new piece on the
// frame it appears (2026-10-18: its 52 measured programs reproduce on the port only that way), and one
// frame later for each frame it sees the piece late. `delay` is that first frame: 1 for a piece seen as
// it appears (y = -0.5), 1 + k for one seen k frames into its fall (y = -0.5 + k * 10/256).
namespace fever::control_moves {
constexpr int bridge_delay = 1;
// Bit 4*x+r: the triple placement (x, r) in Ama's labels is locked by a controller program that presses
// nothing before `delay`. A lower bound: the programs are the port's canonical ones (control::explore).
u32 triple_mask(Field field, const piece::Piece& piece, const rule::Rule& rules, int delay = bridge_delay);
// The buttons (control::Button bits) from frame `delay` until the lock, for the shortest such program;
// nothing when none locks (x, r).
std::optional<std::vector<u8>> triple_program(Field field, const piece::Piece& piece, const rule::Rule& rules,
                                              int x, int r, int delay = bridge_delay);
}

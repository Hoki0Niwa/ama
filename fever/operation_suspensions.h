#pragma once

namespace operation::fever_suspensions {
// 2026-10-14: excluded again at the user's request. The temporary capture
// reactivation was revoked. Ordinary turns/wall kicks and lower floor kicks
// remain enabled. Examples: doc/DISABLED_TRIPLE_OPERATIONS.md.
constexpr bool triple_hooks_enabled = false;
constexpr bool triple_high_lateral_kicks_enabled = false;
// 2026-10-14 (16:10 session, 6 giving-ups, 5 of them triples): the generic "push away from a blocked arm"
// trial also lifts a triple from the spawn row to the 13th row, the climb that `hook` was stopped for. Every
// failed route held such a lift (axis y 0 -> -1 on a turn) and the game turned the piece differently.
constexpr bool triple_spawn_row_lifts_enabled = false;
}

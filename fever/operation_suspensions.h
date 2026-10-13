#pragma once

namespace operation::fever_suspensions {
// 2026-10-14: temporarily enabled at the user's request for overnight
// failure capture. These trial operations have NOT been repaired or accepted.
// Measured examples and resealing points: doc/DISABLED_TRIPLE_OPERATIONS.md.
constexpr bool triple_hooks_enabled = true;
constexpr bool triple_high_lateral_kicks_enabled = true;
}

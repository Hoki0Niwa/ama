#pragma once

namespace operation::fever_suspensions {
// 2026-10-14: excluded again at the user's request. The temporary capture
// reactivation was revoked. Ordinary turns/wall kicks and lower floor kicks
// remain enabled. Examples: doc/DISABLED_TRIPLE_OPERATIONS.md.
constexpr bool triple_hooks_enabled = false;
constexpr bool triple_high_lateral_kicks_enabled = false;
}

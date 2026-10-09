# Observation-based operation API (2026-10-09)

`core/operation.*` owns current-pose rotation and shortest operation routes.
`build.ps1` builds `operations.dll` beside the selected output executable.
The bridge calls the versioned cdecl ABI directly, without waiting for the
placement-search process. Each edge returns input, resulting x/y/r, quick-turn
arming, and nominal input duration (3 frames, or 9 for a sideways kick).
The bridge observes each result and requests a new route on a mismatch.
There is no Python/archive fallback when the library is absent or incompatible.

Coordinates: x=0..5, y=0 at the visible top, floor y=11. ABI 1 reports rule 0
for Tsu and rule 1 for Fever. Tsu accepts pairs only. Fever also accepts triples,
quads and big puyos; quads/big never kick or climb. The two-edge quick turn is
restricted to pairs. Triple push-back is experimental and needs Steam validation.
Tsu pair rules retain the pivot ceiling at row 13. Both libraries are built from
the same source on their separate branches; changes must be ported deliberately.

Fever `special_moves` enables pair/triple placement candidates proven reachable
by this model, including kicks and quick turns. Default solo protocol behavior
is preserved unless this flag is supplied; the live bridge and battle worker
enable it for this trial. Field scoring, timing and Tsu/Fever death rules stay
separate. This verifies a model, not the game's Fever rotation mechanics.

Fever placement evaluation has no special-operation penalty. Nominal frames
are for input scheduling/observation only. The ABI can disable kicks explicitly
for legacy no-kick simulator tests; live sessions enable them by default.

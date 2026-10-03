# Engine integration from Ama Memory Bridge

The `irregular-form` engine incorporates the engine changes developed in
`ama-memory-bridge` through 2026-10-03. It remains a Puyo Puyo Tsu engine and
provides a starting point for a separate Fever version.

## Integrated changes

- Optional beam width/depth, preserving the engine defaults of 250/16.
- Tactical decisions prepare only the construction search they need.
- Construction results can be reused while the opponent's attack changes.
- Spawn-based input paths, predicted next fields, and alternative placements.
- Solo construction and attack candidates, including a precomputed firing reply.
- Runtime BMI2/PEXT selection on GCC, with a software fallback.
- Portable Windows build and standalone engine protocol regression tests.

Evaluation weights and Tsu tactical policies are preserved. The existing
three-visible-pair behavior of `bench`, `puyop`, `test` and `tuner` is retained;
the older versions of those files in the bridge are not imported. Existing
benchmark URL output and comparison/rendering scripts are retained as well.

## Build and check on Windows

```powershell
.\build.ps1
python test/test_engine_protocol.py
.\build.ps1 -Target bench
```

The engine is `bin/pvp/pvp.exe`; run it with `--engine config.json` to serve
JSON lines over stdin/stdout. The existing make targets remain available.
The default release build requires SSE4.1 and selects BMI2 at runtime.
`make PEXT=true pvp` explicitly requires BMI2; `NATIVE=true` opts into a
CPU-specific build.

## Optional JSON protocol fields

The original request/reply fields are still supported. New request fields:

| Field | Default | Meaning |
| --- | --- | --- |
| `beam_width`, `beam_depth` | 250, 16 | Construction beam size |
| `include_path` | false | Spawn route and explicit reachability |
| `include_next` | false | Field, score, chain length and all-clear after the placement |
| `solo` | false | Use construction/attack search without versus tactical policy |
| `fire` | false | In solo mode, select the attack candidate's first placement |
| `reuse_search` | false | Reuse compatible construction results in the same engine process |
| `search_prefix` | 0 | Compare this many queue pairs; 0 compares the entire queue |
| `tactics_only` | false | Return `build_required` before an unprepared beam is needed |

Solo replies can include `fire_reply`, `attack_score` and `attack_chain`.
These attack values describe a chain reachable within the attack search's
visible queue, not necessarily a chain fired by the first placement.
Versus replies expose `search_reused`, `search_reusable` and `build_search`.
`search_ms` is the engine response computation time. Extra fields are additive.

Paths assume the spawn position; the real client must verify the current
position and handle falling, timing and unreachable targets. A partial queue
match intentionally permits a guessed tail and does not promise equivalence
to a fresh search with the full real queue.

## Real game client and Fever

Memory reading, controller backends, observation-based steering, launcher,
prefetch scheduling and challenge timing remain in `ama-memory-bridge`.
They are client components rather than engine dependencies. Its 50/8 automatic
play defaults do not replace this engine's 250/16 defaults.

Fever needs its own piece representation, rules, tactical policy, game-state
protocol and memory profile. Existing fields/cache keys only describe Tsu:
mode transitions, character, piece shape and Fever state must be represented
before reusing searches in a Fever implementation.

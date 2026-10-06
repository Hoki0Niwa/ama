# Frame-based Tsu test matches

The default PVP referee counts **virtual game frames**, without sleeping,
rendering, or polling every frame. It jumps directly to the next decision,
lock, chain link, chain end, or garbage landing. AI search time is wall time
only: a slow computer does not change the simulated result. This is a Tsu
referee; it does not implement Fever.

```powershell
# Original search strength; run multiple matches concurrently.
.\bin\pvp\pvp.exe --games 100 --jobs 2 local local:other.json

# Faster screening: 50-wide, depth-8 search, with the same frame referee.
.\bin\pvp\pvp.exe --games 100 --fast --jobs 2 local local:other.json

# Custom search size and measured timing profile, with an event trace.
.\bin\pvp\pvp.exe --games 10 --beam-width 100 --beam-depth 8 --timing-config pvp/timing.json --log bin/match.jsonl local local

# Cheap screening with substantially less search, before testing full strength.
.\bin\pvp\pvp.exe --games 100 --beam-width 12 --beam-depth 3 --jobs 2 local local

# Reproduce the previous referee's abstract timing for older comparisons.
.\bin\pvp\pvp.exe --games 10 --timing abstract local local
```

`--fast` changes search quality, not game time. The defaults remain 250 x 16.
For precise comparisons, use the same search size on both engines. The
referee sends the size to subprocess engines too; older third-party engines
may ignore these additive protocol fields. Options are applied left to right,
so explicit search sizes after `--fast` override it.

`--jobs` gives each worker its own two engine instances/processes. Seeds and
the starting seat depend on the game number, not worker scheduling. Output
and logs stay in game-number order. A beam search already launches six
branches, so choose jobs according to the available CPU and memory. The
summary reports wall seconds, games per second, simulated seconds (summed
over games), and their ratio to wall time.

## Timing data and limits

The compiled defaults equal [timing.json](timing.json); the file is optional.
`--timing-config` overrides selected keys. Unknown keys and invalid times are
rejected. All durations are integer frames. The profile is provisional,
combining observations with a simple fall model:

| Key | Frames | Basis |
| --- | ---: | --- |
| `fps` | 60 | Bridge's game counter |
| `start` | 11 | First pair appearance in the 2026-10-03 recordings |
| `soft_drop` | 2 / row | Recorded DOWN input |
| `input` | 3 / pulse | Bridge's two held frames + one release frame |
| `wall_kick` | 9 / pulse | Bridge steering model: about 8 frames of slide animation |
| `quick_turn` | 8 extra | Existing Ama path model's animation buffer |
| `next_pair` | 27 | Recorded soft-drop lock to next pair appearance |
| `tear_row` | 18 / row | Approximation, based on the bridge's cited roughly 0.3-second one-row tear; multi-row linear scaling is uncalibrated |
| `vanish` | 55 | Median chain counter increment to score settled flag |
| `chain_drop` | 2 / row | Approximation for fast gravity after a link |
| `chain_ground` | 23 extra when falling | Approximation: together with 55 and a 1–5 row fall it produces the observed 80–88 frame intervals |
| `garbage_drop` | 2 / row | Uncalibrated gravity approximation |
| `garbage_ground` | 32 | Uncalibrated landing approximation |
| `ai_unit` | 41 | Median observed link interval 82 / the AI's 2 units per link |

Local evidence is in the bridge's `SOURCES.md`, `INPUT.md`, and
`observations/chain-info-20261003/rec1.jsonl` / `rec2.jsonl`. A reproducible
counter summary is saved in [timing-observations.json](timing-observations.json):
148 consecutive link intervals (median 82), 61 last-link-to-end intervals
(median 82), and 194 link-to-settled intervals (median 55). This includes
outliers and mixed observed situations; it is not a guarantee for every field.
To repeat the extraction or inspect newer bridge recordings:

```powershell
python pvp/calibrate_timing.py path/to/rec1.jsonl path/to/rec2.jsonl --output bin/timing-observations.json
```

The referee computes actual maximum fall distance after each pop and uses
`vanish + chain_ground + distance * chain_drop` when something falls; a link
without gravity takes `vanish` alone. Scores convert to nuisance one link
at a time, retain their point remainder, offset incoming nuisance, and become
fixed when the sender's chain ends. Simultaneous outgoing links offset each
other before sending. Garbage is checked after the placed pair or completed
chain, capped at 30 per drop. Partial rows choose distinct columns with a
seeded shuffle; this conserves nuisance counts rather than using the search's
worst-case `Field::drop_garbage` approximation.

Steering finds the shortest frame paths with Ama's existing collision and
rotation model. Same-color pairs can use the faster equivalent orientation.
On low fields, inputs and DOWN
overlap; when the path crosses a high stack, steering precedes DOWN. This is
an estimate of lock timing, not frame-by-frame controller emulation. The
referee does not model natural-drop control, pre-input cancellation, the
24–48 frame gauge display delay, margin time, soft-drop scoring, or measured
search/prefetch latency. It shows the resolved field during chains, as the
bridge's engine requests do. Remaining attack time is rounded up through
`ai_unit` into the existing AI protocol's abstract units, with raw game-frame
time also included in decision logs as `enemy_attack_frames`. The AI's
search heuristics themselves retain their abstract timing.

`--log` starts with the timing/search metadata and then records decisions,
locks, individual links, and garbage events. `tick` and `frame` in frame
mode both mean game frames. Decision rows include `lock_frame`; link and
garbage rows include `end_frame`. Abstract mode retains its previous move
and chain row formats, following the new match metadata row.

## Validation

```powershell
.\build.ps1
python test/test_engine_protocol.py
python test/test_pvp_simulator.py
```

The simulator tests compare timed chain scores and final fields with the core
resolver, check nuisance conservation, simultaneous decisions/attacks/deaths,
future attack visibility, arrival timing, per-player move limits, custom
profiles, subprocess search settings, and serial/parallel reproducibility.

## Measured screening throughput

2026-10-04, current Windows workspace build, local vs local, seeds 1–2,
30 placements per player. These are short capped trials. Search size also
changes the chosen placements and simulated duration. Individual results and
commands are saved in [benchmark-20261004.json](benchmark-20261004.json).

| Search | Jobs | Wall seconds for 2 trials | Aggregate simulated seconds / wall seconds |
| --- | ---: | ---: | ---: |
| 250 x 16 | 1 | 90.963 | 0.52 x |
| 50 x 8 (`--fast`) | 1 | 60.818 | 0.73 x |
| 50 x 8 (`--fast`) | 2 | 36.088 | 1.23 x |
| 12 x 3 | 2 | 25.296 | 2.94 x |

50 x 8 serial and parallel trials produced identical results. Two workers
improved throughput by about 1.69 x in that comparison. The 12 x 3 preset is
useful for cheap screening; final strength comparisons should use the desired
production search size. A longer 4-seed, 80-placement run at 250 x 16 exceeded
the 180-second measurement cap, so it is not included as a completed sample.

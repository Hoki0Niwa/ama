<div align="center">

  <h1>Ama</h1>
  <br>
  Strongest Puyo Puyo Tsu AI
  <br>
  <br>
    <a href="https://ko-fi.com/citrus610">
      <img
        src="https://img.shields.io/badge/Ko--fi-Support%20me%20on%20Ko--fi-FF5E5B?logo=kofi&logoColor=white"
        alt="ko-fi"
        height="24em"
      >
    </a>
  <br>

</div>

## Overview
Ama is an AI created to play Puyo Puyo Tsu 1P and PVP. This project aims to become the strongest Puyo Puyo entity. Currently, Ama can run on Puyo Puyo Champions Steam version.

The engine includes the improvements developed in Ama Memory Bridge: configurable
search size, tactical construction reuse, input paths, predicted fields and solo
replies. See [ENGINE.md](ENGINE.md) for the Windows build, protocol extensions,
tests and the boundary between this engine and the separate real-game client.

## Features
- Field representation
  - Bitfield
  - SIMD for fast chain simulation
- Search
  - Best first search
  - Beam search
    - Parallelized search
    - Monte Carlo inspired sampling method with predetermined queues
    - Highest expected chain score selection policy
  - Quiescence search
  - Transposition table
    - Value-preferred with aging replacement scheme
  - Searches from every visible pair (the one in hand and the next 2), sampling the rest of the queue
- Evaluation
  - Chain detection
  - Chain extension
  - Trigger height
  - Field shape
  - Avoid tearing
  - Avoid wasting resources
- Fire policy (`ai/fire.h`)
  - Aims for `ai::TRIGGER` (130,000) and fires as soon as it is in hand
  - Fires whatever is in hand from 74 puyos instead of risking death
- Enemy reading
  - State machine
  - Build action
    - Big chain (78% of chains >= 100,000)
    - Fast second chain
    - All Clear battle
    - Imbalance resources
    - Countering
    - Harassment
  - Attack action
    - Negamax inspired search that can look 3 moves ahead
    - Crush
    - Combo
    - Kill
  - Defense action
    - Negamax inspired search that can look 2 moves ahead
    - Correspondence return
    - Synchronized attack
    - Accepting/Countering
    - Desparate return

## How to build
This project requires `g++` with C++20 support and an SSE4.1 CPU. Default release
builds select BMI2/PEXT at runtime and fall back to software on unsupported CPUs.
`PEXT=true` requires BMI2; `NATIVE=true` makes the build specific to the build CPU.
- On Windows, run `.\build.ps1` to build `bin/pvp/pvp.exe`, then `python test/test_engine_protocol.py`.
- Clone and `cd` to the repository.
- Run `make PEXT=true puyop` to build the puyop client.
- Get the binary in `bin`.
- Run `make PEXT=true bench` to build the batch benchmark for comparing evaluation weights. It plays one game per seed with one flat weight set and appends one line per seed to a TSV file, so the same seed range can be run for several weight files and compared pairwise.
  - Extract a weight profile from `config.json`, e.g. `python3 -c "import json;json.dump(json.load(open('config.json'))['build'],open('build.json','w'))"`
  - Run `bin/bench/bench.exe build.json 1 101 out.tsv` to play seeds 1 to 100.
  - The first 15 columns are: seed, result (`fired` / `dead` / `nomove` / `timeout`), score of the first chain >= 78000 (0 if none), biggest chain score, biggest chain length, moves, frames, time in ms, longest search of the game in ms, then for the chain that ended the game (0 when not fired) `count_fire` (puyos in the field just before it popped), `popped`, `leftover` (`count_fire - popped`), `excess` (`popped - 4 * links`), `max_link` (most puyos in one link) and `wasted` (puyos popped by the chains fired earlier in the game).
  - Four appended columns make the current format 19 columns: `small_clear_moves` counts earlier moves that cleared at least one link; `single_clear_moves` counts their one-link subset. Both exclude the ending big chain and a move that ends in death, and are retained for games that do not fire. `first_130k_move` is the first 1-based move on which the current pair could legally fire at least 130,000 and survive (`-1` if never). `fire_delay_130k` is the actual fire move minus that first opportunity (`0` for immediate fire, `-1` if never ready or not fired). `bench/compare.py` reads 9-, 15- and 19-column files; missing new metrics are shown as unrecorded. The opportunity diagnostic is outside the longest-search timer but included in total game wall time.
  - The AI sees 3 pairs and plays through the fire policy, as in the game. `BEAM_WIDTH`, `BEAM_DEPTH` and `BEAM_TRIGGER` in the environment override the beam search configuration. `QUEUE_VISIBLE` controls known pairs, including the current pair (2..128, capped at beam depth); values above 3 supply the actual future queue for experiments. For example, `BEAM_TRIGGER=95000 QUEUE_VISIBLE=2 bin/bench/bench.exe build.json 1 101 old.tsv` plays with the older visibility and trigger. `BEAM_TARGET`, `BEAM_ZORO` (0/1) and `FIRE_GUARD` (0/1), `FIRE_GUARD_COUNT`, `FIRE_GUARD_SCORE` (the fire policy's late-game guard) override the other search and policy options.
  - `python bench/measure_next.py --exe bin/bench/bench.exe --output docs/benchmarks/next-count-run --next-counts 3 6 12 16 --seeds 40 --jobs 2` compares known NEXT counts on the same seeds and saves a manifest, TSVs, field snapshots and a summary. It resumes completed games if interrupted. The search horizon stays fixed; a fully known horizon uses one beam search, while partially known horizons use six sampled tails. This measures perfect future information, rather than the accuracy of a prediction from remaining color counts.
  - The benchmark uses exact sampled-tail lengths so odd NEXT counts do not add an extra search ply. Production retains its existing tail-length rounding. See the [40-seed NEXT comparison](docs/benchmarks/next-count-20261005/README.md) for results and timing conditions.
  - To explore beyond 16 known pairs, also raise `--depth`, e.g. `--next-counts 36 --depth 36 --seeds 10 --jobs 1`. See the [16/24/36-pair comparison](docs/benchmarks/next36-20261005/README.md). Summaries include game time divided by moves and the longest decision; use serial runs for timing comparisons.
  - One game takes about 6 seconds on a 4-core machine, so 500 seeds for one weight file is roughly 50 minutes.
  - Add a 6th argument to also save the field of every game, e.g. `bin/bench/bench.exe build.json 1 13 out.tsv 100 fields.txt`. For a fired game it is the complete chain with the triggering pair placed, otherwise the last position reached.
  - `python3 bench/render.py -o shapes.svg before=fields_before.txt after=fields_after.txt` draws the saved fields side by side (one row per weight set, one column per seed) to compare the shapes built from the same queue. It only needs the Python standard library.
- Run `make PEXT=true pvp` to build the PVP simulator. It plays two engines against each other with the same queue, using virtual game frames and skipping directly between events, sending nuisance with 70 points per puyo, offsetting, all clear bonus and a loss when the 3rd column reaches the 12th row.
  - `bin/pvp/pvp.exe --games 30 --seed 1 local local:other.json` matches two weight files of this build.
  - `bin/pvp/pvp.exe --games 30 local "path/to/other/pvp.exe --engine path/to/other/config.json"` matches this build against another build of the AI: any command that speaks the JSON line protocol documented in `pvp/main.cpp` can be an engine, and `pvp --engine` serves that protocol for its own build. Build the simulator in both source trees to compare two versions.
  - Each line of the output is one game: winner, reason (`death`, `garbage`, `no_move`, `max_moves`), length, moves, biggest chain and nuisance sent per side. `--verbose` also prints the final fields and `--log moves.jsonl` writes every request, reply and chain as JSON lines.
  - The referee plays the role of the game client for the AI's `trigger` and `stretch` arguments: the AI stretches its chain while its field holds fewer than 60 puyos, then fires as soon as a chain worth the trigger is available, and the trigger is lowered at 70 and 74 puyos so the AI fires what it has instead of overflowing (see the constants in `pvp/main.cpp`). The AI's own fire policy handles the danger zone before these limits.
  - `--fast` uses a smaller 50 x 8 search for quick screening; `--beam-width W --beam-depth D` sets it explicitly (default 250 x 16). `--jobs N` runs independent matches concurrently, preserving seed and log order. Neither option introduces real-time waits.
  - `--timing-config pvp/timing.json` applies an adjustable frame profile; `--timing abstract` reproduces the previous referee. Measured and approximate timings, event logs, and limitations are documented in [pvp/TIMING.md](pvp/TIMING.md). Margin time and controller/prefetch latency are not simulated.

NOTE: The source code for the `Puyo Puyo Champions Steam` isn't available to prevent cheating

## Acknowledgement
- Thanks K. Ikeda, D. Tomizawa, S. Viennot and Y. Tanaka for their paper `Playing PuyoPuyo: Two search algorithms for constructing chain and tactical heuristics`. Ama's early search algorithm was heavily influenced by their work.
- Thanks [puyoai](https://github.com/puyoai/puyoai) for the fast implementation of bitfield and the inspiration for the evaluation function.
- Thanks [takapt](https://www.slideshare.net/slideshow/ai-52214222/52214222) for their beam search idea, Ama's new improved beam search was based on their implemntation.
- Thanks [nlohmann](https://github.com/nlohmann/json) for the c++ json library.
- Thanks [nicoshev](https://github.com/Nicoshev/rapidhash) for their `rapidhash` hash function.

## License
This project is licensed under [MIT LICENSE](LICENSE).


## Optional human-form evaluation

The `irregular-form` branch can optionally use the original `main` beam evaluator's
GTR, SGTR and FRON pattern matching. Set `build.form` in `config.json` to a positive
integer to enable it; `50` is the original `main` weight. The best match of the three
patterns contributes its matching score times this weight. These are one shared
bias, not separate per-pattern weights. The original mismatch penalty and
bottom-left garbage suppression are retained.

The default is `build.form = 0`: pattern matching is skipped and irregular-form
behavior remains the default. Legacy configs without `form` also default to zero.
Other evaluation weights, including `shape`, remain independent. Ama Memory Bridge's
launcher can edit these weights per AI and save them in its presets without changing
this repository's config. Restart bridge sessions after changing engine/config.

After building with `build.ps1`, run `python test/test_engine_protocol.py` for protocol
regressions and `python test/test_form_evaluation.py` for native form evaluation and
legacy-config compatibility checks. The latter uses MinGW g++ by default; `AMA_CXX`
can select another compiler. Its `.cc` harness is compiled separately from the
existing simulation target.

## Solo chain quality

The current solo objective is to make scores above 130,000 more consistent, retain
opportunities to reach 150,000, and reduce repeated small clears that delay firing.
The default trigger stays at 130,000; raising it to 150,000 is no longer the proposed
default. The earlier 150,000 experiments remain documented in
[docs/challenge-150k.md](docs/challenge-150k.md).

`build.clear_cost` charges actual score points per colored puyo cleared by a
candidate's first move, when that move scores less than 5,000. This counts only the
clear that will certainly happen if the move is chosen. A first move scoring at
least 5,000 has no such cost. Uncertain future clears retain the existing action
and position evaluation; completed clears are not charged again at the next decision.
This is separate from `build.score`, which evaluates excess puyos within a planned
chain. The candidate's raw score, target attainment and fire thresholds are preserved.
Legacy configs without `clear_cost` use zero and keep the previous ranking.

The new cost defaults to zero. In the 40-seed comparison, a cost of 1,200 reduced
single-link clears by about 20%, but also reduced 130,000 attainment from 22 to 20
games. A cost of 300 did not reduce small clears. Neither setting demonstrated the
desired combination, so the existing default behavior is retained. See the measured
results and saved TSV files in [docs/challenge-150k.md](docs/challenge-150k.md).

Use `python bench/compare.py --summary-only before=before.tsv after=after.tsv` to
compare scores, small clears and firing delays without field snapshots or Pillow.
Run `python test/test_chain_quality.py` for the native small-clear regression checks.

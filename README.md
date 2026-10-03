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
  - Columns: seed, result (`fired` / `dead` / `nomove` / `timeout`), score of the first chain >= 78000 (0 if none), biggest chain score, biggest chain length, moves, frames, time in ms, longest search of the game in ms.
  - The AI sees 3 pairs and plays through the fire policy, as in the game. `BEAM_WIDTH`, `BEAM_DEPTH` and `BEAM_TRIGGER` in the environment override the beam search configuration and `QUEUE_VISIBLE=2` shows it only 2 pairs, e.g. `BEAM_TRIGGER=95000 QUEUE_VISIBLE=2 bin/bench/bench.exe build.json 1 101 old.tsv` plays like the previous versions.
  - One game takes about 6 seconds on a 4-core machine, so 500 seeds for one weight file is roughly 50 minutes.
  - Add a 6th argument to also save the field of every game, e.g. `bin/bench/bench.exe build.json 1 13 out.tsv 100 fields.txt`. For a fired game it is the complete chain with the triggering pair placed, otherwise the last position reached.
  - `python3 bench/render.py -o shapes.svg before=fields_before.txt after=fields_after.txt` draws the saved fields side by side (one row per weight set, one column per seed) to compare the shapes built from the same queue. It only needs the Python standard library.
- Run `make PEXT=true pvp` to build the PVP simulator. It plays two engines against each other with the same queue, counting time in the AI's own unit (one pair = 1, one chain link = 2), sending nuisance with 70 points per puyo, offsetting, all clear bonus and a loss when the 3rd column reaches the 12th row.
  - `bin/pvp/pvp.exe --games 30 --seed 1 local local:other.json` matches two weight files of this build.
  - `bin/pvp/pvp.exe --games 30 local "path/to/other/pvp.exe --engine path/to/other/config.json"` matches this build against another build of the AI: any command that speaks the JSON line protocol documented in `pvp/main.cpp` can be an engine, and `pvp --engine` serves that protocol for its own build. Build the simulator in both source trees to compare two versions.
  - Each line of the output is one game: winner, reason (`death`, `garbage`, `no_move`, `max_moves`), length, moves, biggest chain and nuisance sent per side. `--verbose` also prints the final fields and `--log moves.jsonl` writes every request, reply and chain as JSON lines.
  - The referee plays the role of the game client for the AI's `trigger` and `stretch` arguments: the AI stretches its chain while its field holds fewer than 60 puyos, then fires as soon as a chain worth the trigger is available, and the trigger is lowered at 70 and 74 puyos so the AI fires what it has instead of overflowing (see the constants in `pvp/main.cpp`). The AI's own fire policy handles the danger zone before these limits.
  - Margin time and the real frame timing of the game are not simulated.

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

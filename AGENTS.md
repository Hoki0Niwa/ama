# Development ownership

- This repository is the authoritative source for Ama's AI, evaluation, search, simulation, engine API and engine builds.
- Implement engine improvements here, rather than in the archived copy at `C:\Users\ho_ki\git\ama-memory-bridge\ama`.
- `C:\Users\ho_ki\git\ama-memory-bridge` owns memory reading, virtual controllers, observation-based operation, prefetch scheduling, launcher and integration tests. Its default engine/config are this repository's `bin/pvp/pvp.exe` and `config.json`.
- After engine changes, rebuild with this repository's `build.ps1` and run `python test/test_engine_protocol.py`. Restart bridge sessions to use the rebuilt binary; do not copy it into the archived bridge directory.
- Keep Tsu and Fever behavior distinct. Implement Fever on its own branch/worktree with appropriate rule/state/protocol changes; do not make the Tsu bridge silently run an incompatible Fever engine.

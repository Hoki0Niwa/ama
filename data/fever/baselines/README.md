# 計測・再生の記録

生成：`data/fever/baselines/*.json` の一覧（ファイル名の日付順）。各ファイルの「状態」は、その記録が自分で述べている適用範囲である。
実機の受入れを意味する記録はここにはない。記録の経緯は `doc/WORK_LOG.md` の同じ日付の項にある。

回帰の基準（記録済み要求と返答）は `data/fever/golden/` にあり、`python tools/fever_check.py replay` が使う。

| ファイル | KB | 状態（ファイル内の記述） | 種類 |
| --- | --- | --- | --- |
| `2026-10-05-animation.json` | 0 | candidate_offsets_not_formal_profile | — |
| `2026-10-05-garbage-timing-build.json` | 3 | — | Prototype state search and partially measured timing; CPU me |
| `2026-10-05-live-duel.json` | 4 | — | Fever two-AI live calibration entry, not full T13 acceptance |
| `2026-10-05-t14-reference.json` | 76 | controlled_reference_geometry_not_live_success_rate | — |
| `2026-10-05-t14.json` | 2 | T14_engine_prototype_not_live_acceptance | — |
| `2026-10-05-t15-live-seeds.json` | 44 | read_only_real_seed_geometry_replay_not_live_acceptance | — |
| `2026-10-05-t15-observation.json` | 3 | read_only_live_observation_not_ai_control_acceptance | — |
| `2026-10-05-timing-calibration.json` | 466 | adopted_empirical_timing_v1 | — |
| `2026-10-05-timing-cpu.json` | 314 | measured_samples_not_general_law | — |
| `2026-10-05-timing-extended.json` | 3893 | measured_samples_not_general_law | — |
| `2026-10-05-timing.json` | 66 | measured_samples_not_general_law | — |
| `2026-10-05.json` | 3 | — | — |
| `2026-10-06-fever-build-prefetch.json` | 34 | offline_log_board_synthetic_enemy_not_live_acceptance | — |
| `2026-10-06-fever-chain-timing.json` | 259 | measured_exact_edges_drawn_geometry_and_score_verified | — |
| `2026-10-06-fever-counter.json` | 134 | controlled_builder_move_public_seed_model_not_live_acceptance | — |
| `2026-10-06-fever-deadlines.json` | 24 | — | — |
| `2026-10-06-fever-extension.json` | 119 | native_model_replay_and_controlled_queues_not_live_acceptance | — |
| `2026-10-06-fever-garbage-ready.json` | 4 | steam_observed_fever_nonclear_drop_to_next_operable_piece_not_universal_bound | — |
| `2026-10-06-fever-garbage-repair-validation.json` | 150 | native_model_replay_and_controlled_visible_queues_not_live_acceptance | — |
| `2026-10-06-fever-input-anomalies.json` | 69 | historical_log_not_post_fix_live_acceptance | — |
| `2026-10-06-fever-long-extension.json` | 926 | synthetic_visible_three_model_clock_replay_not_live_acceptance | — |
| `2026-10-06-fever-opening-carry-log.json` | 25 | historical_log_not_post_fix_live_acceptance | — |
| `2026-10-06-fever-small-garbage-replay.json` | 188 | model_replay_only_running_ai_unchanged | — |
| `2026-10-06-fever-tactics-replay.json` | 7 | — | — |
| `2026-10-06-fever-wait.json` | 10 | — | — |
| `2026-10-06-fever-watch-failure-replay.json` | 53 | model_replay_only_running_ai_unchanged | — |
| `2026-10-06-fever-watch-initial.json` | 67 | recording | — |
| `2026-10-06-fever-watch-latest.json` | 179 | recording | — |
| `2026-10-06-mode-control.json` | 2 | — | — |
| `2026-10-06-mode-latency.json` | 1 | — | 8 recorded normal requests; cached next boards are synthetic |
| `2026-10-06-mode-reliability.json` | 0 | — | — |
| `2026-10-06-mode-reproduction.json` | 8 | — | user-operated live matches, read-only observer; no controlle |
| `2026-10-06-normal-build-bench.json` | 2 | offline_prototype_colour_model_no_opponent | — |
| `2026-10-06-normal-colors.json` | 116 | recorded_snapshots_model_replay_not_win_rate_or_live_acceptance | — |
| `2026-10-06-refactor-baseline-entry.json` | 4 | offline_prototype_colour_model_modelled_clock_not_live | — |
| `2026-10-06-refactor-baseline-seed.json` | 75 | offline_prototype_colour_model_modelled_clock_not_live | — |
| `2026-10-06-refactor-overflow-rule.json` | 3 | offline_replay_not_live_acceptance | nuisance_overflow_above_row_13_is_not_a_loss |
| `2026-10-07-p2-entry-objectives.json` | 4 | offline_prototype_colour_model_scripted_nuisance_not_live_and_not_a_battle_result | tools/bench_fever_baseline.py entry |
| `2026-10-07-p3-entry-tactics.json` | 3 | offline_prototype_colour_model_scripted_nuisance_not_live_and_not_a_battle_result | tools/bench_fever_baseline.py entry |
| `2026-10-07-p4-entry-tactics.json` | 2 | offline_prototype_colour_model_scripted_nuisance_not_live_and_not_a_battle_result | tools/bench_fever_baseline.py entry |
| `2026-10-07-p5-fever-strategies.json` | 5 | offline_prototype_colour_model_public_reference_seeds_modelled_clock_not_live | tools/bench_fever_baseline.py fever |

# 作業ルール

## 対象と進め方

- 作業前に `doc/README.md`、`doc/IMPLEMENTATION_PLAN.md`、`doc/WORK_LOG.md` が存在する場合は読み、現在の対象範囲と未完了事項を確認する。
- 全体の目標はぷよぷよeスポーツ（Steam版）のフィーバールールで戦うAI。現在の対象は段階A：全キャラの形状周期に対応し、ラフィーナの特殊な組ぷよでとこぷよの大連鎖を組むAI。フィーバーのゲージ・時計・種・対戦処理は段階B以降とし、`doc/IMPLEMENTATION_PLAN.md` のロードマップと作業順序（T0〜T7）に従う。
- 2026-10-03 のユーザー指示により実装段階に入った。土台は `irregular-form` ブランチで、`fever` へマージ済み（T0）。
- 全キャラの形状周期は `data/fever/dropsets.json` と `doc/DROPSETS.md` にある。状態が `unknown` や未照合のキャラを確認済みと推定しない。
- 作業の区切りで `doc/WORK_LOG.md` に日付、依頼、変更、確認したこと、未確認事項、次の作業を追記する。過去の記録は原則として残し、訂正は追記で明示する。
- 計画や仕様の変更があれば該当文書も更新する。実装、ビルド成功、実行確認、目標達成は区別し、未実施の検証を完了扱いしない。
- `doc/` の計画・仕様・作業記録と `data/` はGitで管理し、依頼されたコミット・pushの対象に含める。2026-10-01のユーザー指示により、従来の除外方針を変更した。文書がない別のチェックアウトでは、実施済みだと推定しない。

## ブランチの分離（Tsu と Fever を混ぜない）

- マージは `irregular-form` → `fever` の一方向だけ。`fever` のコミットを `irregular-form` や `main` に取り込まない。
- Tsu エンジンの改良は `irregular-form` で行う。`fever` で既存ファイルの共通化が必要になったら、ルールに依存しない形で `irregular-form` に先にコミットし、`fever` に取り込む。
- フィーバー固有のコードは新規ファイル（`core/piece.*`、`core/dropset.*`、`core/rule.h`、`fever/`、`bench_fever` など）に閉じ込め、既存ファイルへの変更は Tsu の挙動を変えない範囲にとどめる。
- Tsu の挙動は `python test/test_engine_protocol.py` と `bench` の同一シード結果で固定し、`fever` での作業後に変わっていないことを確認する。
- フィーバーは別バイナリ（`bin/fever/fever.exe`）として実装し、Tsu 用の `bin/pvp/pvp.exe` とそのプロトコルは壊さない。ローカルでは `fever` 用に別 worktree を使うとビルド成果物と `config.json` が衝突しない。

## エンジンとブリッジの所有範囲（irregular-form より）

- This repository is the authoritative source for Ama's AI, evaluation, search, simulation, engine API and engine builds.
- Implement engine improvements here, rather than in the archived copy at `C:\Users\ho_ki\git\ama-memory-bridge\ama`.
- `C:\Users\ho_ki\git\ama-memory-bridge` owns memory reading, virtual controllers, observation-based operation, prefetch scheduling, launcher and integration tests. Its default engine/config are this repository's `bin/pvp/pvp.exe` and `config.json`.
- After engine changes, rebuild with this repository's `build.ps1` and run `python test/test_engine_protocol.py`. Restart bridge sessions to use the rebuilt binary; do not copy it into the archived bridge directory.
- Keep Tsu and Fever behavior distinct. Implement Fever on its own branch/worktree with appropriate rule/state/protocol changes; do not make the Tsu bridge silently run an incompatible Fever engine.

# 作業ルール

## 対象と文書

- 作業前に `doc/README.md` と `doc/IMPLEMENTATION_PLAN.md` を読み、対象範囲と未完了事項を確認する。
- 全体の目標はぷよぷよeスポーツ（Steam版）のフィーバールールで戦うAI。このブランチ（`fever`）の対象は、通常盤面の大連鎖構築、フィーバー中のタネ探索、攻防判断と実機接続。単独構築の基盤に加え、protocol 3の対戦AIを実装している。
- 仕様・計画は該当文書を直接更新し、現在の説明を一つにする。古い仕様、完了した作業手順、日付ごとの追記は残さない。変更履歴・依頼の経緯・コミットの記録はGit/GitHubで確認する。作業日誌は作成しない。
- 実装、ビルド成功、自動検証、実機確認、目標達成を区別する。検証条件と残る制約は `doc/VALIDATION.md`、研究の比較結果は研究用の仕様・結果文書にまとめる。再現ツールが読む文書を移動する際は参照先も更新する。未実施の検証を完了扱いしない。
- 全キャラの周期は `data/fever/dropsets.json` と `doc/DROPSETS.md` を参照する。`unknown` や未照合を確認済みと推定しない。`steam` は16手の確認を表すが、隠し2キャラ以外は選択画面の図との照合で、実際に置いた確認ではない。modの要求に `pattern` がある場合はその周期を使う。
- `doc/` と `data/` はGit管理対象。ただし `data/fever/baselines/` はGitに載せず、ローカルの測定証拠・バックアップから参照する。別checkoutに証拠がない場合は存在や検証済みを推定しない。

## ブランチの分離（Tsu と Fever を混ぜない）

- マージは `irregular-form` → `fever` の一方向だけ。`fever` のコミットを `irregular-form` や `main` に取り込まない。
- Tsu エンジンの改良は `irregular-form` で行う。`fever` で既存ファイルの共通化が必要になったら、ルールに依存しない形で `irregular-form` に先にコミットし、`fever` に取り込む。
- フィーバー固有のコードは新規ファイル（`core/piece.*`、`core/dropset.*`、`core/rule.h`、`fever/`、`bench_fever` など）に閉じ込め、既存ファイルへの変更は Tsu の挙動を変えない範囲にとどめる。
- Tsu の挙動は `python test/test_engine_protocol.py` と `bench` の同一シード結果で固定し、`fever` での作業後に変わっていないことを確認する。
- フィーバーは別バイナリ（`bin/fever/fever.exe`）として実装し、Tsu 用の `bin/pvp/pvp.exe` とそのプロトコルは壊さない。ローカルでは `fever` 用に別 worktree を使うとビルド成果物と `config.json` が衝突しない。

## エンジンとブリッジの所有範囲（irregular-form より）

- This repository owns Ama's AI, evaluation, search, engine API and engine builds. The separate fever-simulator repository owns the full Fever match simulator.
- Implement engine improvements here, rather than in the archived copy at `C:\Users\ho_ki\git\ama-memory-bridge\ama`.
- `C:\Users\ho_ki\git\ama-memory-bridge` owns memory reading, virtual controllers, observation-based operation, prefetch scheduling, launcher and integration tests. Its default engine/config are this repository's `bin/pvp/pvp.exe` and `config.json`.
- After engine changes, rebuild with this repository's `build.ps1` and run `python test/test_engine_protocol.py`. Restart bridge sessions to use the rebuilt binary; do not copy it into the archived bridge directory.
- Keep Tsu and Fever behavior distinct. Implement Fever on its own branch/worktree with appropriate rule/state/protocol changes; do not make the Tsu bridge silently run an incompatible Fever engine.

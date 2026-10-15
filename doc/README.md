# Fever文書

## 現在の対象

初回本線の目標得点@40手を改善する研究。S0Gを比較基準とし、次の候補は通常構築の教師初期化と小規模PPO。製品への統合と学習は未実施。

実装の有無と実機での受入れは分ける。残る作業は [実装計画](IMPLEMENTATION_PLAN.md)、確認範囲は [検証](VALIDATION.md) を参照。

## 文書一覧

| 目的 | 文書 |
| --- | --- |
| 次の作業と完了条件 | [実装計画](IMPLEMENTATION_PLAN.md) |
| ルール・出典・仮定 | [ルール](RULES_AND_ASSUMPTIONS.md)、[対戦の得点・相殺](FEVER_BATTLE_RULES.md) |
| キャラの形状周期 | [ドロップセット](DROPSETS.md) |
| 配置・回転・上端・敗北条件 | [物理モデル](FEVER_PHYSICS.md)、[操作API](../docs/OPERATIONS.md) |
| 単独構築・protocol 1・ベンチ | [単独エンジン](FEVER_ENGINE.md) |
| 対戦判断・protocol 3 | [対戦エンジン](FEVER_MODE_ENGINE.md)、[Feverへの攻撃](FEVER_DISRUPTION.md) |
| 通常のみのprotocol 2と再生 | [通常対戦API](FEVER_BATTLE_ENGINE.md) |
| 起動と先読み・入力 | [実機接続](FEVER_MODE_LIVE.md) |
| 観測値とメモリの制約 | [実機観測](FEVER_MODE_OBSERVATION.md) |
| 連鎖・ちぎり・予告判定の時間 | [時間モデル](FEVER_TIMING.md) |
| テスト・証拠・未確認事項 | [検証](VALIDATION.md) |
| 初回構築の研究契約・再現 | [得点ベンチマーク](FEVER_FIRST40_BENCHMARK.md) |
| 研究の測定結果 | [構築研究の結果](RESEARCH_RESULTS.md) |
| ベンチが保存する再現仕様 | [実験契約](contracts/README.md) |
| 次の研究工程 | [構築学習・自己対戦計画](SELFPLAY_RL_PLAN.md) |

## 文書の管理

仕様や残件は該当箇所を更新する。日付付きの追記、完了済み計画、引き継ぎ日誌は増やさず、経緯は [GitHubの変更履歴](https://github.com/Hoki0Niwa/ama/commits/codex/fever-first40-benchmark/) を使う。測定結果は条件・分母・限界とともに必要な結論を残す。

`doc/` はFeverの仕様、`docs/` は共通エンジンの補助資料。各ブランチの文書はそのcheckoutの実装を説明する。研究用の凍結モデルを製品版と同一視しない。

機械可読の正本は `data/fever/` の `dropsets.json`、`scoring.json`、`timing.json`、`mode_rules.json`、`battle_policy.json`。`baselines/` はGit除外のローカル証拠で、cloneだけでは揃わない。バックアップは `C:/Users/ho_ki/git/ama-baselines-backup/` を参照し、欠けた証拠は未確認とする。

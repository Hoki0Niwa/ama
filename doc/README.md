# Fever文書

## 現在の対象

通常盤面の大連鎖構築、フィーバー中のタネ探索、攻防判断と実機接続。単独構築の基盤に加え、protocol 3の対戦AIを実装している。

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
| 症状の局所再現 | [調査・再現手順](DEBUGGING.md) |
| 3個組の操作制限 | [停止中の操作と測定済み許可](DISABLED_TRIPLE_OPERATIONS.md) |
| 2個組の高段経路例 | [空中横移動](PAIR_AIRBORNE_ROUTE.md) |
| 自己対戦・学習環境 | [独立シミュレーター](FEVER_SIMULATOR_REPOSITORY.md) |

## 文書の管理

仕様や残件は該当箇所を更新する。日付付きの追記、完了済み計画、引き継ぎ日誌は増やさず、経緯は [GitHubの変更履歴](https://github.com/Hoki0Niwa/ama/commits/fever/) を使う。測定結果は条件・分母・限界とともに必要な結論を残す。

`doc/` はFeverの仕様、`docs/` は共通エンジンの補助資料。各ブランチの文書はそのcheckoutの実装を説明する。研究用の凍結モデルを製品版と同一視しない。

機械可読の正本は `data/fever/` の `dropsets.json`、`scoring.json`、`timing.json`、`mode_rules.json`、`battle_policy.json`。`baselines/` はGit除外のローカル証拠で、cloneだけでは揃わない。バックアップは `C:/Users/ho_ki/git/ama-baselines-backup/` を参照し、欠けた証拠は未確認とする。

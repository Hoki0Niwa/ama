# ぷよぷよフィーバー対応AI：計画・作業記録

最終更新：2026-10-04

## 現在の方針

amaを土台に、ぷよぷよeスポーツ（Steam版）のフィーバールールで戦えるAIを作る。全体のロードマップは次の5段階で、段階Aの実装を進める。T0〜T5（基盤・Piece・dropset・保守的な配置と遷移モデル・色列・探索・エンジン・計測）は完了。2026-10-04に共通基盤の速度改善を統合した。次はT6の調整。色列は試作用モデルでSteam版を再現していない。特殊ツモの実機入力と未確認の上端条件は [FEVER_PHYSICS.md](FEVER_PHYSICS.md) に記載。

| 段階 | 内容 | 状態 |
| --- | --- | --- |
| A | 全キャラの形状周期に対応し、ラフィーナで単独の大連鎖を組む（とこぷよ） | 実装開始 |
| B | フレーム単位の時間モデルとキャラ別倍率表 | 未着手 |
| C | フィーバー中の連鎖のタネを発火するソルバー | 未着手 |
| D | ゲージ・タイム・連続相殺を含む対戦戦略。自己対戦による調整を併用 | 未着手 |
| E | 形状別の入力経路とクライアント接続 | 未着手 |

土台は `irregular-form` ブランチで、2026-10-03 に `fever` へマージ済み。エンジンJSONプロトコル、発火方針、見える3ツモからの探索、計測・対戦ツール、可搬ビルドをそのまま使う。Tsu と Fever を混ぜないための運用は `AGENTS.md` の「ブランチの分離」を参照。

## 文書

| 文書 | 内容 |
| --- | --- |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | 土台の選択、現コードの改装点、設計、段階Aの作業順序と完了条件、評価方針、段階B〜E |
| [RULES_AND_ASSUMPTIONS.md](RULES_AND_ASSUMPTIONS.md) | フィーバールールの仕様、ツモの種類と回転、盤面ルール、色列、出典と未確定事項 |
| [DROPSETS.md](DROPSETS.md) | 全24キャラと隠し2キャラの形状周期、表記、確認状況 |
| [FEVER_PHYSICS.md](FEVER_PHYSICS.md) | T2の座標・配置・ちぎり・14段目消滅・保守的な到達判定と未確認事項 |
| [FEVER_ENGINE.md](FEVER_ENGINE.md) | T3〜T5の色列モデル・探索・発火方針・エンジンのプロトコル・`bench_fever` の出力と検証範囲 |
| [WORK_LOG.md](WORK_LOG.md) | 依頼・決定・変更・検証の履歴と次の作業 |

機械可読データ：[`data/fever/dropsets.json`](../data/fever/dropsets.json)

## リポジトリと状態

- 正本リポジトリ：`C:\Users\ho_ki\git\ama`
- Feverの作業先：`C:\Users\ho_ki\git\ama-fever`
- 作業ブランチ：`fever`
- 計画作成時の基準コミット：`dea210bcd92965ae08fbc311f23565b0fab6dbbb`（v2.0.1）
- 土台にするブランチ：`irregular-form`（Tsu エンジンの改良。詳細は同ブランチの `ENGINE.md`）
- 元リポジトリ：https://github.com/citrus610/ama
- `fever` の実装コードは `irregular-form` のマージ分と、Linux ビルド修正（`form.h` の `_countof` → `std::size`）に加え、共通基盤の速度改善、`core/piece.h`・`core/dropset.*` を含む。
- 共通基盤のSIMD演算・連鎖評価の高速化と置換表のメモリ解放を実装・検証済み。Feverの特殊ツモの表現・周期参照・配置と遷移モデル・ツモ生成・探索・単独用エンジン（`bin/fever/fever.exe`）・計測（`bench_fever`）は実装済み。重みの調整、時間・ゲージ・対戦処理、入力経路は未実装。
- 速度改善の変更・測定・再現手順：[SPEED_REFACTOR.md](SPEED_REFACTOR.md)。
- 別の作業フォルダーには中断された未検証の試作があるが、このforkには移植していない。参考にする場合も、仕様確認・レビュー・検証から行う。

## 文書の管理

`doc/` の計画・仕様・作業記録と `data/` のデータはGit管理対象とし、コミット・pushしてリモートから参照できるようにする。

作業開始時に本書と計画・直近の作業記録を読み、作業終了時に記録を追記する。仕様や方針を変更した場合は、理由と影響も残す。

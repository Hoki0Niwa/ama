# ぷよぷよフィーバー対応AI：計画・作業記録

最終更新：2026-10-05

2026-10-05の最新指示：ユーザーが入力停止問題の解決を申告し、T14への着手を希望した。通常対戦の未照合・T13受入れを残したまま、フィーバーモードのエンジン側試作へ進んだ。ゲージ・時計・盤面保管／復帰・二種類の予告・タネソルバー・protocol 3を実装し自動検証した。実機統合とT14全体の完成は未確認。[T14の実装・出典・検証範囲](FEVER_MODE_ENGINE.md)。

## 現在の方針

amaを土台に、ぷよぷよeスポーツ（Steam版）のフィーバールールで戦えるAIを作る。全体のロードマップは次の5段階で、段階Aの実装を進める。T0〜T7（基盤・Piece・dropset・保守的な配置と遷移モデル・色列・探索・エンジン・計測・調整）は完了。2026-10-04に共通基盤の速度改善を統合した。T7で全26キャラの周期をSteam版と照合し、りすくまを訂正した。段階AのT0〜T7は完了。色列は試作用モデルでSteam版を再現していない。特殊ツモの実機入力と未確認の上端条件は [FEVER_PHYSICS.md](FEVER_PHYSICS.md) に記載。

| 段階 | 内容 | 状態 |
| --- | --- | --- |
| A | 全キャラの形状周期に対応し、ラフィーナで単独の大連鎖を組む（とこぷよ） | T0〜T7完了。Claudeの採用評価値を維持し最新版を再ビルド。T8の受入れを確認中 |
| B | フレーム単位の時間モデルとキャラ別倍率表 | 全26キャラの通常倍率を資料から転記し試作計算を追加。実機の得点照合・対戦時間の校正は未完了 |
| C | フィーバー中の連鎖のタネを発火するソルバー | T14の可視3ツモ・CPU予算付き試作を実装。公開50盤面で幾何を確認。実機受入れは未完了 |
| D | ゲージ・タイム・連続相殺を含む対戦戦略。自己対戦による調整を併用 | ゲージ加算0の通常対戦審判・再生・即時相殺に着手。実機との一致と共通攻防の拡張は未完了 |
| E | 形状別の入力経路とクライアント接続 | 単独連鎖構築用の実験版接続・操作改善が先行。対戦統合は未完了 |

土台は `irregular-form` ブランチで、2026-10-03 に `fever` へマージ済み。エンジンJSONプロトコル、発火方針、見える3ツモからの探索、計測・対戦ツール、可搬ビルドをそのまま使う。Tsu と Fever を混ぜないための運用は `AGENTS.md` の「ブランチの分離」を参照。

## 文書

評価値調整後から対戦完成までの具体的な順序は [BATTLE_ROADMAP.md](BATTLE_ROADMAP.md) のT8〜T16に従う。まず両者の相殺時のゲージ増加を0にし、フィーバー突入のない対戦を実機で完成させる（T13）。その後、ゲージ・時計・タネ・盤面切替を追加する（T14）、フィーバーを含む実機統合（T15）、全26キャラの総合受入れ（T16）へ進む。全キャラを共通の探索・評価・判断で卒なく扱い、周期と倍率はキャラ別データとして参照する。キャラ専用の評価値・戦術調整は後回しにする。T8〜T13の着手版は実装したが、実機対戦の完成判定は未達。

| 文書 | 内容 |
| --- | --- |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | 土台の選択、現コードの改装点、設計、段階Aの作業順序と完了条件、評価方針、段階B〜E |
| [BATTLE_ROADMAP.md](BATTLE_ROADMAP.md) | T8〜T16：ゲージ増加0の対戦を先に完成し、フィーバー機能を追加して全キャラ共通AIを受け入れる |
| [RULES_AND_ASSUMPTIONS.md](RULES_AND_ASSUMPTIONS.md) | フィーバールールの仕様、ツモの種類と回転、盤面ルール、色列、出典と未確定事項 |
| [DROPSETS.md](DROPSETS.md) | 全24キャラと隠し2キャラの形状周期、表記、確認状況 |
| [FEVER_PHYSICS.md](FEVER_PHYSICS.md) | T2の座標・配置・ちぎり・14段目消滅・保守的な到達判定と未確認事項 |
| [FEVER_ENGINE.md](FEVER_ENGINE.md) | T3〜T6の色列モデル・探索・発火方針・エンジンのプロトコル・`bench_fever` の出力・調整結果と検証範囲 |
| [FEVER_BATTLE_ENGINE.md](FEVER_BATTLE_ENGINE.md) | T8〜T13の着手版、通常対戦プロトコル・共通判断・自己対戦・再生・残る実機統合 |
| [FEVER_MODE_ENGINE.md](FEVER_MODE_ENGINE.md) | T14のモード審判・タネ探索・protocol 3、Web出典と公開タネ検証、実機統合の残件 |
| [FEVER_BATTLE_RULES.md](FEVER_BATTLE_RULES.md) | 通常倍率・攻撃・相殺・落下・全消しの試作仕様と出典、実機での未確認事項 |
| [FEVER_TIMING.md](FEVER_TIMING.md) | 接地・ちぎり・連鎖中落下の実測、探索に採用した範囲、対CPU測定への切替 |
| [WORK_LOG.md](WORK_LOG.md) | 依頼・決定・変更・検証の履歴と次の作業 |

機械可読データ：[`dropsets.json`](../data/fever/dropsets.json)、[`scoring.json`](../data/fever/scoring.json)、[`timing.json`](../data/fever/timing.json)、[`battle_policy.json`](../data/fever/battle_policy.json)、[T8の基準記録](../data/fever/baselines/2026-10-05.json)、[実機AI同士対戦の記録](../data/fever/baselines/2026-10-05-live-duel.json)。

対CPUの長時間測定は[追加抽出記録](../data/fever/baselines/2026-10-05-timing-extended.json)に配置4310件・リンク間隔1202件を保存した。[時間仕様v1](../data/fever/baselines/2026-10-05-timing-calibration.json)で列別の距離・量による連鎖時間と操作再開を校正し、探索へ採用した。実測誤差は±2フレーム以内、未測定の高段差と入力経路時間は推定を明示する。対戦の完成判定は未達。詳細は [FEVER_TIMING.md](FEVER_TIMING.md)。

2026-10-05追記：ブリッジに「フィーバーAI同士の対戦（実測用）」を追加した。ユーザーが両者のフィーバーカウント0を設定し、ラフィソル対アリィで両AIの配置とアリィ勝利の結果画面（最大12連鎖・フィーバー回数0）を確認した。共通の単独構築AIを2本接続した実測用入口で、相手への攻防判断とprotocol 2の実機接続は未統合。詳細は [FEVER_BATTLE_ENGINE.md](FEVER_BATTLE_ENGINE.md) とブリッジの `FEVER.md`。T13の全キャラ受入れは未完了。

## リポジトリと状態

- 正本リポジトリ：`C:\Users\ho_ki\git\ama`
- Feverの作業先：`C:\Users\ho_ki\git\ama-fever`
- 作業ブランチ：`fever`
- 計画作成時の基準コミット：`dea210bcd92965ae08fbc311f23565b0fab6dbbb`（v2.0.1）
- 土台にするブランチ：`irregular-form`（Tsu エンジンの改良。詳細は同ブランチの `ENGINE.md`）
- 元リポジトリ：https://github.com/citrus610/ama
- `fever` の実装コードは `irregular-form` のマージ分と、Linux ビルド修正（`form.h` の `_countof` → `std::size`）に加え、共通基盤の速度改善、`core/piece.h`・`core/dropset.*` を含む。
- 共通基盤のSIMD演算・連鎖評価の高速化と置換表のメモリ解放を実装・検証済み。Feverの特殊ツモの表現・周期参照・配置と遷移モデル・ツモ生成・探索・単独用エンジン（`bin/fever/fever.exe`）・計測（`bench_fever`）は実装済み。別入口の `fever_battle/` で通常対戦へ着手した。実機への接続はブリッジ側（`ama-memory-bridge/FEVER.md`）に単独用実験版があり、シェゾで14連鎖の発火を確認した。対戦入口と実時間の入力経路の統合は未完了。
- 速度改善の変更・測定・再現手順：[SPEED_REFACTOR.md](SPEED_REFACTOR.md)。
- 別の作業フォルダーには中断された未検証の試作があるが、このforkには移植していない。参考にする場合も、仕様確認・レビュー・検証から行う。

## 文書の管理

`doc/` の計画・仕様・作業記録と `data/` のデータはGit管理対象とし、コミット・pushしてリモートから参照できるようにする。

作業開始時に本書と計画・直近の作業記録を読み、作業終了時に記録を追記する。仕様や方針を変更した場合は、理由と影響も残す。

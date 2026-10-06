# ぷよぷよフィーバー対応AI：計画・仕様・作業記録

最終更新：2026-10-07

## 現在の状態

ぷよぷよeスポーツ（Steam版）のフィーバールールで、ゲージ増加ありの対戦を protocol 3 のエンジンで判断する。**いまエンジンがどう判断するかは [FEVER_MODE_ENGINE.md](FEVER_MODE_ENGINE.md)（現行仕様）にまとめてある。** 日ごとの経緯は [WORK_LOG.md](WORK_LOG.md) にあり、本書には載せない。

- **通常盤面**：予告も相手連鎖もなければ本線を構築する。フィーバーは通常盤面の本線が最も大事であり（2026-10-07ユーザー）、構築の目的は本線構築に固定している。予告または相手連鎖があるときは、積む・最小相殺・本線発火・受けるを1つの探索で比べる。
- **フィーバー中**：すべての手順を「このフィーバーが終わるまでに見込める得点」で比べる（方針 `value`）。
- **確認の範囲**：Fever系の自動テスト220件、記録済み要求の再生、オフラインの計測まで。上の2つの判断を入れた後の実機での入力・勝敗は、文書上は未確認。代表キャラでの先行対戦（[BATTLE_ROADMAP.md](BATTLE_ROADMAP.md) の順序4）は、2026-10-06にユーザーが完了といってよい状態と申告している。
- **リファクタリング**：[REFACTOR_PLAN.md](REFACTOR_PLAN.md) のR0〜R6（R3・R6は一部）と、[SEARCH_PLAN.md](SEARCH_PLAN.md) の探索の再編（P0〜P6）を実施した。残りと理由は各書の末尾の節にある。
- **検証の入口**：`python tools/fever_check.py test`（全テスト）、`python tools/fever_check.py replay`（記録済み要求と同じ返答をするか）、`python tools/bench_fever_baseline.py`（計測）。

## 現在の方針

amaを土台に、ぷよぷよeスポーツ（Steam版）のフィーバールールで戦えるAIを作る。全体のロードマップは次の5段階で、段階Aの実装を進める。T0〜T7（基盤・Piece・dropset・保守的な配置と遷移モデル・色列・探索・エンジン・計測・調整）は完了。2026-10-04に共通基盤の速度改善を統合した。T7で全26キャラの周期をSteam版と照合し、りすくまを訂正した。段階AのT0〜T7は完了。色列は試作用モデルでSteam版を再現していない。特殊ツモの実機入力と未確認の上端条件は [FEVER_PHYSICS.md](FEVER_PHYSICS.md) に記載。

状態の欄は2026-10-05時点の記述で、その後の進み具合は上の「現在の状態」と [BATTLE_ROADMAP.md](BATTLE_ROADMAP.md) を見る。

| 段階 | 内容 | 状態 |
| --- | --- | --- |
| A | 全キャラの形状周期に対応し、ラフィーナで単独の大連鎖を組む（とこぷよ） | T0〜T7完了。Claudeの採用評価値を維持し最新版を再ビルド。T8の受入れを確認中 |
| B | フレーム単位の時間モデルとキャラ別倍率表 | 全26キャラの通常倍率を資料から転記し試作計算を追加。実機の得点照合・対戦時間の校正は未完了 |
| C | フィーバー中の連鎖のタネを発火するソルバー | T14の可視3ツモ・CPU予算付き試作を実装。公開50盤面で幾何を確認。実機受入れは未完了 |
| D | ゲージ・タイム・連続相殺を含む対戦戦略。自己対戦による調整を併用 | ゲージ加算0の通常対戦審判・再生・即時相殺に着手。実機との一致と共通攻防の拡張は未完了 |
| E | 形状別の入力経路とクライアント接続 | 単独連鎖構築用の実験版接続・操作改善が先行。対戦統合は未完了 |

土台は `irregular-form` ブランチで、2026-10-03 に `fever` へマージ済み。エンジンJSONプロトコル、発火方針、見える3ツモからの探索、計測・対戦ツール、可搬ビルドをそのまま使う。Tsu と Fever を混ぜないための運用は `AGENTS.md` の「ブランチの分離」を参照。

## 文書

具体的な実施順は [BATTLE_ROADMAP.md](BATTLE_ROADMAP.md) 第2節の先行工程に従う。通常対戦の30試合受入れ・端数列順等の網羅的校正を待たず、フィーバーありの操作接続と共通戦術を先行する。入力に必要な実盤面・状態整合・経路の確認は先行工程に含め、未観測値を確定値で埋めない。全キャラは共通の探索・評価・判断で扱い、周期と倍率をキャラ別データとして参照する。T8〜T16の未完了の校正・受入れと、キャラ専用調整を後回しにする方針は維持する。

| 文書 | 内容 |
| --- | --- |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | 土台の選択、現コードの改装点、設計、段階Aの作業順序と完了条件、評価方針、段階B〜E |
| [BATTLE_ROADMAP.md](BATTLE_ROADMAP.md) | フィーバー狙い・伸ばしを使う実機対戦を先行し、T8〜T16の残る校正・総合受入れへ進む |
| [REFACTOR_PLAN.md](REFACTOR_PLAN.md) | リポジトリ全体のリファクタリングの計画と実施結果（領域と作業ブランチ、課題R1〜R9、調査結果、実施したもの・しなかったもの） |
| [SEARCH_PLAN.md](SEARCH_PLAN.md) | 探索と評価の再編の計画と実施結果（相殺ストック、通常盤面の戦術探索、フィーバー中の `value`、計測値、決定事項） |
| [RULES_AND_ASSUMPTIONS.md](RULES_AND_ASSUMPTIONS.md) | フィーバールールの仕様、ツモの種類と回転、盤面ルール、色列、出典と未確定事項 |
| [DROPSETS.md](DROPSETS.md) | 全24キャラと隠し2キャラの形状周期、表記、確認状況 |
| [FEVER_PHYSICS.md](FEVER_PHYSICS.md) | T2の座標・配置・ちぎり・14段目消滅・保守的な到達判定と未確認事項 |
| [FEVER_ENGINE.md](FEVER_ENGINE.md) | T3〜T6の色列モデル・探索・発火方針・エンジンのプロトコル・`bench_fever` の出力・調整結果と検証範囲 |
| [FEVER_BATTLE_ENGINE.md](FEVER_BATTLE_ENGINE.md) | T8〜T13の着手版、通常対戦プロトコル・共通判断・自己対戦・再生・残る実機統合 |
| [FEVER_MODE_ENGINE.md](FEVER_MODE_ENGINE.md) | **現行仕様。** protocol 3 のエンジンの構成、要求と返答、通常盤面とフィーバー中の判断、値の構成、出典、検証方法、未確認事項 |
| [FEVER_MODE_LIVE.md](FEVER_MODE_LIVE.md) | protocol 3 の操作接続（起動、先読みと先行入力、未知のおじゃま履歴、確認範囲） |
| [FEVER_MODE_OBSERVATION.md](FEVER_MODE_OBSERVATION.md) | モード状態・時計・予告・保管盤面の実機観測と残件 |
| [FEVER_MARGIN_TIME.md](FEVER_MARGIN_TIME.md) | マージンタイムの出典と扱い、放置対戦の収録。失敗発火の延期と復旧の規則（2026-10-07に削除した当時の記録） |
| [FEVER_BATTLE_RULES.md](FEVER_BATTLE_RULES.md) | 通常倍率・攻撃・相殺・落下・全消しの試作仕様と出典、実機での未確認事項 |
| [FEVER_TIMING.md](FEVER_TIMING.md) | 接地・ちぎり・連鎖中落下の実測、探索に採用した範囲、対CPU測定への切替 |
| [SPEED_REFACTOR.md](SPEED_REFACTOR.md) | 共通基盤の速度改善の変更・測定・再現手順 |
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

`docs/`（複数形）は `irregular-form` から取り込んだTsu側の文書と計測記録で、フィーバーの文書は `doc/` に置く。

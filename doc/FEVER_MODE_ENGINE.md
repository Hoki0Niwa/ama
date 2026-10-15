# Fever対戦エンジン（protocol 3）

`python -m fever_battle.mode_engine` が通常構築・攻防・タネ探索を統合する。判断の係数は `data/fever/battle_policy.json`、倍率は `scoring.json`、時間は [FEVER_TIMING.md](FEVER_TIMING.md) を参照。値は対戦での最適化が済んだものではない。

## 構成

| 部品 | 責務 |
| --- | --- |
| `mode_engine.py` | 要求検査、振り分け、先読みと入力承認 |
| `bin/fever_battle/fever_battle.exe` | `solo` 構築・通常戦術・タネ探索・盤面遷移を処理するnative worker |
| `fever/search.*`・`fire.*`・`engine.*` | 単独エンジンと共通の構築・発火 |
| `transition.h`・`normal_defense.h` | 得点・相殺・予告・落下・防御と時系列 |
| `mode.py`・`model.py` | 明示イベントの審判、ゲージ・時計・保管盤面 |

通常のみの [protocol 2](FEVER_BATTLE_ENGINE.md) と [単独API](FEVER_ENGINE.md) は別入口。

## 要求・返答

1行JSON。`protocol_version: 3`、`rule: "fever_battle"` を必須とする。

両席に盤面、現在手＋NEXT2、キャラ、周期位置、予告、`mode`、`gauge`、`mode_generation`、`seed_id`、`prepared_frames`、`remaining_frames`、`clock_running`、`seed_base`、`seed_chain`、`stored_field` を渡す。通常／Feverの確定・未確定予告は4値で別に保持し、操作中モードの `confirmed/unconfirmed` と一致させる。

観測不能値を0にしない。`garbage_phase`・`moves_since_chain`・Fever途中の準備時間など、許される未知値はnullと `_status: "unknown"` で表す。要求の `pattern` はキャラ別周期の上書き。検査の正本は `mode_engine.py` と `protocol.py`。

| op | 動作 |
| --- | --- |
| `think`（既定） | 現在の判断 |
| `prepare`・`prepare_normal`・`prepare_observed` | 既知の次状態で先に判断を用意 |
| `recover_placement` | `reachable_placements` に限って再選択 |
| `score`・`predict_chain`・`referee` | 得点・相手連鎖予測・明示イベント再生 |
| `ready` | 初期化完了を返す。探索・状態更新なし |

返答は `action: "place"` または `"wait"`。でかぷよは `color` を含む。`wait` を配置として実行しない。`reason`・`decision_kind` は診断値で、依存関係は `decision_dependencies` に持つ。入力前に `authorize_mode_reply()` で現在の盤面・ツモ・モード・世代・予告・時計・攻撃期限を照合する。

## 可視情報と時間の制約

- 色は現在手＋NEXT2だけを使い、先の色は仮想列と区別する。未知タネ・突入先・全消し交換後は確定探索しない。
- 端数列カーソルが既知ならその順序で落とす。不明なら全組合せを評価し、実落下後に再観測する。仮の落下盤面を `next_field` として返さない。
- 観測した相手の連鎖はリンク別に一度予測し、得点済みを再送しない。確定時刻と自盤面への落下時刻を分ける。
- CPU時間による構築・戦術・種探索の打切りは行わず、設定した幅・深さ・ノードで探索量を制限する。旧 `decision_budget_ms`／`budget_ms` は探索完了時間の保証ではない。workerの通信故障検出は別。
- Fever時計、マージン、連鎖終了、実際の着弾期限はゲーム時間として検査する。

## 通常盤面の構築と発火

通常は最長本線を構築し、初回からキャラ別通常倍率で候補・実発火を評価する。重みは `config.json` のFever設定。仮想6列のビームと、可視ツモでの実発火探索を使い分ける。設定した深さと実際に完了した深さは区別する。

初回の目標・panic・容量条件は `solo_options` と要求に従う。初回目標−1以上（下限4）の通常連鎖を実観測した後、またはFever経験後に再構築へ移る。小連鎖の掃除や、準備返答だけで初回完了としない。

セカンドの `second_target_chain` 指定時は構築と発火の目標をそろえる。省略時は初回目標−1（既定14）、明示nullは容量まで構築する。安全な非消去配置がなくなると連鎖数を問わず容量発火を探す。目標未満の容量発火を目標達成には数えない。

可視の本線を保持・延長できる配置と発火を比較する。自然な1〜2連鎖の整理を一律に禁止せず、未完成本線を小さい攻撃で失う経路を抑える。`upper_12`／`upper_13` と `waste_14` はFever構築で無効。2・5列13段を一律には候補除外せず、物理経路と死亡列の余白で判断する。

## 通常盤面の防御・戦術

可視3ツモで、構築・受ける・最小相殺・本線発火・突入を同じ時系列で比較する。各手で操作時間・ちぎり・リンク得点・相殺・相手イベント・非消去時の落下（最大30個）を進める。未知端数列の通常探索は落下後の架空盤面へ進まない。

受入れは盤面の実配置と既知の未到着攻撃で検査する。本線を自発的に消費する費用と、おじゃまで壊される結果を区別する。安全に受けられる少量予告だけを理由に、十分返しの優先群で本線を消費しない。必要防御・唯一の救済・構築自身の目標発火は維持する。

判断結果は温存 `build`、防御成立 `defense`、未確定 `unresolved`、探索不能 `unavailable` を区別する。`current_*` は初手、`projected_*` は可視後続を含む結果。現在生存していることを、未知色まで含む防御保証にはしない。

通常相手にはゲージ増加へ一般加点せず、双方未突入なら自分の突入を避け、本線を残す副砲で相手の突入を促す。相手の実Fever経験後は合戦の返しへ切り替える。十分な本線返し同士は実得点優先、同点なら短時間。推定kill比率だけで構築を上書きせず、互換の `projected_kill` は0。

全消し目的の加点は開始8手以内・Fever未経験・観測最大4未満、消す色ぷよ16以下・3連鎖以下に限る。全消しの実効果、必要相殺、構築の発火を禁止する条件ではない。

相手Feverへの攻撃は [FEVER_DISRUPTION.md](FEVER_DISRUPTION.md)。`finish_probe` は可視経路と全端数列で救済の有無を検査し、逃げがなければ最短決着を選ぶ。出現列が塞がる場合は観測した現在姿勢が必要。

## Feverのタネ探索

実盤面・可視3ツモの配置列を探索し、最初に消した所でタネ交換として打ち切る。規定未満の掃除でも交換し、同じタネの掃除後を継続しない。

基本方針 `value` は、現在の連鎖得点、残り時計で消化できる後続タネの期待点、終了時に持ち越す段、有害な保留予告で比較する。消さない手は実盤面の発火口・必要色数・残りツモと空きに基づく見込みを使う。可視ツモが残る間はその続きの最善値を使う。

後続タネは標準リンクと成功見込みによる近似で、実タネの予知ではない。大きいタネを伸ばす際は盤面の空きによる失敗リスクを加味する。値の係数は `fever_seed.value_model`。

原則は伸ばしを比較する。相手の通常盤面へ実際に降らせる余剰がある場合と、相手もFever中で通常用の保留予告がある場合に規定以上の早い発火を優先する（`press_reason`）。規定発火が見えなければ通常の値で比べる。全消しの実利益も扱う。

不明端数列での落下後は最悪の生存・発火口の盤面で可視先を比較するが、返す経路は落下時点で切る。観測中の相手の未送信分は短い手・長い手の両方へ同じ全量を含める。時計0でも実際に操作可能なら現在手を返す。

`seed_forecast.alternatives` に規定発火・失敗発火・非消去の最良値、`extension_potential` に待つ連鎖と見込みを返す。成功保証や未知タネの予測値ではない。

## 先読みとイベント審判

構築結果と最終判断の再利用を分ける。相手連鎖中でも自盤面・キュー・設定が一致する構築部分は利用でき、出現時の戦術は最新観測で再計算する。相手の実質状態・攻撃・着弾・期限が変わる判断は再承認する。

Feverの相手解析は突入・タネ到着・発火イベントで固定し、絶対終了フレームを保持する。経過時間だけで終了時刻を先へずらさない。古い先読み状態で新しい解析を上書きしない。

`ModeReferee` は明示された `enter`・`seed`・`exit`・`clock` を処理する。周期位置はモードで戻さない。これは全対戦の自動schedulerではなく、完全自己対戦は別リポジトリが担当する。

検証と残件は [VALIDATION.md](VALIDATION.md)、起動・入力は [FEVER_MODE_LIVE.md](FEVER_MODE_LIVE.md)。

## 満杯付近の本線保持と実機向け設定

`normal_build` の `retain_floor`／`retain_cells` で可視本線を保護し、`retain_fire_cells`／`retain_fire_chain`、残る安全配置数 `retain_fire_safe_moves` で保持継続と発火を比較する。`forced_lookahead` は置き場所が尽きる前の可視救済、`opening_fire_ramp` は初回の充填に応じた発火連鎖を扱う。条件と現行値は方針JSONと `_normal_options`／`_forced_lookahead` が正本。

相手連鎖中の余裕を使う `_window_build` は、既に選ばれた `jab`／`overpower` を構築で上書きしない。`unready_main` は実際に撃った本線で判定し、埋めた分は費用へ残す。押し発火の下限は `press_min_held=30`、`press_min_lands=6`。いずれも実戦効果の校正は未完了。

測定済み3個組の持ち上げは要求の `lift_allow` を使う。条件・キャッシュ世代・実機確認範囲は [操作制限](DISABLED_TRIPLE_OPERATIONS.md) を参照。`arrival` の時間診断と通常確認余裕は [時間モデル](FEVER_TIMING.md)。

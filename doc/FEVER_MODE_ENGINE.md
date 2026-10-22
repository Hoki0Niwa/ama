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
| `prepare`・`prepare_normal`・`prepare_observed` | 既知の次状態で先に判断を用意。`prepare` 系は任意の `ahead_piece`（置いた後にNEXT2になる、表示前のツモ）を受け取り、次の判断を3ツモで用意する。出現したツモが一致するときだけ再利用する。`prepare` は今のツモが動き出す時に送られるので、次のツモの判断は1手分（実測のペース、なければ最速の1手：置く・ちぎり・出現）後の時刻で行い、相手の連鎖・時計・レートの予定もその分進める。ペースは連続する2手の `think` どうし、または `prepare` どうしの間隔で測る（用意した答えで決まる手は `think` を送らない）。置いている間に相手の連鎖が終わる（確定がこの手のおじゃま判定より前。判定時刻もペースで見積もる）ときは、送られた分を `advance_enemy` と同じく数えて確定させ、確定分を端数列カーソルどおりに落とした盤面で判断を用意する。置く手が連鎖を起こす場合は判断を用意せず（`build_only`）、連鎖後の盤面に、相殺後に残る確定予告（連鎖中に終わる相手の連鎖の分を含む）を落とした予想盤面で、通常盤面の構築探索だけを先に行って残す。端数列が不明で落下後の盤面を決められないときは、落下前の盤面で構築探索だけを残す。出現時の判断は観測から改めて行い、盤面が予想どおりなら構築探索を再利用する |
| `recover_placement` | `reachable_placements` に限って再選択 |
| `score`・`predict_chain`・`referee` | 得点・相手連鎖予測・明示イベント再生 |
| `ready` | 初期化完了を返す。探索・状態更新なし |

返答は `action: "place"` または `"wait"`。でかぷよは `color` を含む。`wait` を配置として実行しない。`reason`・`decision_kind` は診断値で、依存関係は `decision_dependencies` に持つ。入力前に `authorize_mode_reply()` で現在の盤面・ツモ・モード・世代・予告・時計・攻撃期限を照合する。

## 通常戦術の要求単位の指定

`think`、`prepare` 系、`recover_placement` のトップレベルに任意の `normal_tactics` オブジェクトを渡せる。方針JSONを変更せず、その要求とその先読みだけに適用する。省略または `{}` は従来の判断を維持する。子項目は部分指定でき、省略した値は現在の方針を継承する。null、未知のキー、型違い、範囲外は `ValueError`（JSON入口では既存のエラー返答）になる。整数にbooleanや小数は使えない。

| 項目（`normal_tactics.` 以下） | 型・範囲 | 省略時 |
| --- | --- | --- |
| `invite_fever` | boolean | 双方通常かつ双方 `mode_generation == 0` のときtrue |
| `avoid_own_fever` | boolean | 同上 |
| `harass` | boolean | true（探索の許可。必ず撃つ指定ではない） |
| `harass_min_count` | 整数 0〜84 | 24（以上） |
| `harass_max_count` | 整数 0〜85 | 52（未満） |
| `harass_min_height` | 整数 0〜14 | 4（以上） |
| `harass_columns` | 整数 1〜6 | 左から3列 |
| `window_build` | 下記のオブジェクト | 方針JSONを継承 |
| `window_build.enabled` | boolean | 方針JSONに非空の設定があればtrue（現在true） |
| `window_build.hold` | 整数 1〜19 | 現在10 |
| `window_build.min_pieces` | 整数 1〜100 | 現在3 |
| `window_build.fire_pieces` | 整数 0〜100 | 現在4（0で窓内の即発火を無効） |
| `window_build.beam_width` | 整数 1〜10000 | 現在30 |
| `weights` | 下記の整数値のオブジェクト | 方針JSONの各値 |

`harass_min_count <= harass_max_count` が必要。同値なら通常の範囲条件を満たさない。個数・高さはおじゃまを含む。通常の妨害は予告のない局面で、個数の範囲と指定列すべての最低高さを満たすときに探索する。従来の「再構築期の埋まった相手への処理」は別の許可条件で、範囲の外でも残す。`harass: false` は両方を無効にする。相手がFever中なら一般のharassは無効で、タネ交換への攻撃を使う。

明示指定した非空オブジェクトでは、従来の「再構築期の静かな盤面は戦術探索を省く」「色ぷよ17〜23個は省く」という入口を外す。これにより初回以外でも切替と範囲の指定が評価される。ゲージ満杯・相殺加算なしなどの探索不能条件は維持する。`invite_fever` は相手の突入を促す評価、`avoid_own_fever` は自分の突入を避ける評価であり、突入を強制・禁止するものではない。

`weights` の受理キーと現在の既定値（評価式は `tactics.cpp` の `Weights`）：

| キーと現在値 | 型・範囲 |
| --- | --- |
| `entry=6000`, `gauge=1000`, `stock=40`, `color=60`, `drop=150`, `consume=12` | 各整数 0〜1000000 |
| `mainline=1120`, `height=300`, `early=1500`, `builder=250`, `step=400`, `exposed=700` | 各整数 0〜1000000 |
| `pending=0`, `uncountered=2500`, `fever_reach=100`, `harass=400`, `all_clear=5000`, `disrupt=3000` | 各整数 0〜1000000 |
| `mainline_min=4` | 整数 1〜19 |
| `arrival_pieces=2` | 整数 0〜100 |

方針JSONの `kill` は `Weights` では使っておらず要求で受理しない。上表の値は現行既定の説明で、調整結果や戦術の有効性を示さない。

```json
{"normal_tactics":{"invite_fever":true,"avoid_own_fever":false,"harass":true,"harass_min_count":20,"harass_max_count":54,"harass_min_height":3,"harass_columns":3,"window_build":{"enabled":false},"weights":{"entry":4000,"disrupt":5000}}}
```

通常モードの判断返答には `normal_tactics` を追加する。`selected` は最終採用した `reason`（構築・戦術・窓内の構築／発火・回復・観測待ちを含む）、`disruption_kind` は採用した戦術候補の攻撃区分（なければ `none`）。`effective` は解決した切替・閾値・重み、`evaluated_switches` は戦術探索へ渡した `invite_fever`、`avoid_own_fever`、盤面条件適用後の `harass`。探索を省略した場合はnullで、指定値が評価されたと誤認しない。先読みの一致検査と入力承認にも `normal_tactics` を含め、変更した要求に古い判断を流用しない。

## 通常相手への潰し・催促ととどめ（任意）

`normal_tactics.pressure` は潰し・催促を1つの戦術として扱う。`normal_tactics.finish` はとどめ。双方とも `enabled` の既定はfalseで、省略時の配置選択は従来のまま。いずれかを有効にすると、旧 `harass` の誘い加点と `finish_buried` の加点を置き換える。旧加点が新しいタネ・防御条件を迂回することを防ぐ。既定は自分の予告がない通常盤面、相手の通常盤面を対象にする。`pressure.allow_pending` で自分に予告がある局面も許可できる。相手の連鎖中・操作中・Fever中・突入直前は相手の可視相殺探索の対象外で、既存の防御・Fever妨害の判断を使う。

以下は `normal_tactics.` 以下の追加項目。各オブジェクトは部分指定できる。型・範囲・未知キーを検査する。既定値と範囲の正本は `fever_battle/normal_pressure_options.py`。

| 項目 | 型・範囲 | 既定値と意味 |
| --- | --- | --- |
| `pressure.enabled` | boolean | false |
| `pressure.max_chain` | 整数1〜19 | 2。送信した各連鎖の上限 |
| `pressure.min_send` / `max_send` | 各整数1〜1000000 | 6 / 30。新規送信の累積範囲、両端を含む。min <= max |
| `pressure.min_remaining` | 整数0〜84 | 24。撃った後に残す色ぷよ数（おじゃまを除く） |
| `pressure.min_heights` | 整数0〜13を6個の配列 | [4,4,4,3,3,3]。左から各列の最低高さ（おじゃまを含む） |
| `pressure.max_redundancy` | 整数0〜84 | 4。送信した各連鎖の盤面変化の上限 |
| `pressure.third_column_height` | 整数0〜13 | 8。残余の全段分を加えた相手3列目の高さがこれを超えたら埋める圧力を加点 |
| `pressure.block_seed_chain` | 整数1〜19 | 8。相手がFever経験済みかつseed_chainがこの値以上なら、残余を確認できない攻撃、またはゲージ逃げできる攻撃は加点しない |
| `pressure.weight` | 整数0〜1000000 | 400。試作の圧力評価の倍率 |
| `pressure.allow_pending` | boolean | false。予告がある局面でも、新規送信が残る攻撃を評価 |
| `pressure.preempt` | boolean | false。自分の本線が間に合わない場合の先制加点を許可 |
| `pressure.race_margin_frames` | 整数0〜10000 | 0。自分の本線の見積時刻に加える余裕 |
| `pressure.min_enemy_points` | 整数1〜1000000000 | 2100。先制を検討する相手の可視得点の下限 |
| `pressure.preempt_bonus` | 整数0〜1000000 | 0。先制条件成立時の評価単位（`preempt=true` と併用） |
| `pressure.counter_cost_weight` | 整数0〜1000000 | 1。相殺で消す色ぷよ（最大18個）の評価単位 |
| `pressure.gauge_weight` | 整数0〜1000000 | 6。相殺で突入できる場合の評価単位 |
| `pressure.gauge_gain_weight` | 整数0〜1000000 | 0。新規送信による相手ゲージ増分1目盛りの評価単位 |
| `pressure.surplus_weight` | 整数0〜1000000 | 0。完全探索で確認できた相殺後の余剰（最大30個）1個の評価単位 |
| `pressure.max_main_loss` | 整数0〜84 | 84。可視経路で自分から失う保持本線の累積リンク数の上限。0で本線を保護、84は従来どおり制限しない |
| `pressure.max_attacks` | 整数0〜100 | 0。催促の送信連鎖回数の上限。0は制限なし |
| `pressure.attacks_used` | 整数0〜1000000 | 0。同じ催促で既に撃った回数。呼出側が実行済みの送信連鎖だけを数えて渡す |
| `finish.enabled` | boolean | false |
| `finish.min_send` | 整数1〜1000000 | 6。とどめに必要な新規送信の下限 |
| `finish.weight` | 整数0〜1000000 | 30000。条件を満たしたとどめの加点 |
| `counter_read.depth` | 整数1〜3 | 3。相手の可視ツモを読む最大手数 |
| `counter_read.max_nodes` | 整数1〜100000 | 4000。相手配置の探索上限 |

実装は `fever_battle/normal_pressure.*`。相手のキャラ別通常倍率、群・色ボーナス、端数、相手側レート予定、ちぎり、リンク時刻を使い、合法な可視配置を読む。Tsuの `gaze` の得点は使用しない。`defence_1` は1手の、`defence_2` は指定した可視手数の、着弾時刻までの最大相殺量で、mainの1手／4手・3／6連鎖の制限とは異なる。可視を超える4手目の色を補わない。特殊形状も実配置で得点計算する。

相殺を強いる圧力は、着弾までに送信分を返せる観測経路の最小色ぷよ消費 `counter_cost_cells` で評価する。本線に使える資源を使わせ、飽和連鎖量を下げる機会の近似であり、実際に何リンク減るかや相手が必ず相殺することの保証ではない。突入を促す加点は既存の `invite_fever` にも従う。撃った後の自分の資源条件は全て要求で調整できる。大きなタネへの再突入を助けるだけの攻撃は、探索不十分で残余が不明な場合も抑える。残余があっても相殺でゲージが満ちるなら、Feverへ逃げられるので同じく抑える。3列目を埋める加点もゲージ逃げがない場合に限る。

先制は、`counter_read` で実際に置けた可視経路の最大累積得点と、それを得る相対フレームを使う。同点は早い経路。自分はFever通常倍率で再得点した本線の見込みに、自キャラの通常倍率で1リンク4個の得点を足して相手の点数に届くまでの不足リンクを求める。不足を可視ツモの平均個数と自分の設置ペースで補う時間、配置・リンク時間を足す。19リンクまで足しても届かなければ見積時刻を1000000Fとする。自分の見積時刻＋余裕が相手より遅く、自分の送信連鎖終了が相手の得点時刻以前なら先制加点する。これは未知色を確定しない楽観的な成長近似で、相手の本線完成時刻や実着弾の保証ではない。探索不足でも見つけた相手の得点は先制の根拠に使うが、未探索の返しを「ない」と扱わず、余剰・とどめの根拠にはしない。

評価は従来の埋没加点に、相殺費用×`counter_cost_weight`、突入可否×`gauge_weight`、新規送信のゲージ増分×`gauge_gain_weight`、確認できた余剰×`surplus_weight`、先制条件×`preempt_bonus` を足し、`weight` を掛ける。ゲージの2加点は `invite_fever` に従う。`max_main_loss` は既存の本線保護の対象（`weights.mainline_min` 以上）から減るリンクを測り、必要相殺による既存の費用減免前の値を使う。非消去で発火口を埋めた損失も含み、おじゃま落下の損失は含めない。`consumed_cells` は本線以外も含む色ぷよ消費で、失ったリンクと区別する。Fever通常倍率とその時刻のレートで送信量を求めるため、同じ少量送信でもTsuより資源を多く要する場合がある。

`max_attacks` は `attacks_used`＋可視経路内の新規送信連鎖数に適用する。非消去の準備手は数えず、一連鎖内の複数リンクは1回。先読み・取消・回復で回数が増えないよう、エンジン内部では実行回数を記憶しない。呼出側は実行を観測して更新し、催促終了や局の変更時に0へ戻す。何手空けたら別の催促とするかは呼出側の方針であり、回数を省略して渡すと判断をまたぐ上限は効かない。相性と強さの選択もPPFAI側の責務で、Amaに相性表はない。

とどめは相手のゲージが既に7、または相殺リンクで7に届く経路があれば無効。着弾後に始める連鎖も相殺に使えるため、最初の非消去・落下までの経路を含めて検査する。相手に有利に、既存予告を払わずに全得点を新規送信の相殺へ使え、連鎖終了後の盤面で受けられるものとする。それでも全経路・全端数列で最大30個の1回の落下を耐えられないときだけ加点する。探索上限、可視不足、連鎖中・配置中の相手などで判定できない場合は、とどめにしない。相殺加算が0なら、相殺してもゲージは増えない。

非消去の準備手には可視後続の評価を使える。現在の発火は、その発火自身が得た加点と種類を上限とし、後続の本線やとどめを理由に現在の小消しを採用しない。必要防御・生存の優先は既存のまま。

返答理由は `tactics_pressure`、`tactics_finish`、`tactics_prepare_finish`。候補の `normal_attack` が初手、`projected_normal_attack` が可視後続の評価。最終返答の `normal_tactics.normal_attack` は発火する手では初手、準備手では後続の評価を転記する。`kind` は `preempt` / `surplus` / `invite` / `force_counter` / `bury` / `finish` / `none`。`blocked` は最初の不成立条件、`blocked_conditions` は同時に検査した不成立条件の配列（`no_send`、`enemy_unavailable`、`pending`、`min_remaining`、`min_heights`、`max_redundancy`、`max_chain`、`min_send`、`max_send`、`max_main_loss`、`max_attacks`、`large_seed_gauge_only`、`zero_weight`、`no_pressure_value`）。先に打ち切った場合は後段の検査結果を含めない。`main_loss_links`、`consumed_cells`、`attacks` が自分の費用と送信回数、`race` が両者の得点・時刻と先制条件の診断。`counter` に上記の防御量、連鎖終了まで許した `full_counter`、`counter_cost_cells`、既存予告だけの場合と比べた最大追加ゲージ `gauge_gain`、`entry_possible`、`complete`、`cutoff`、`expanded`、残余を返す。`complete` は可視と配置上限で必要な反応経路を覆えたかを表し、未知なら防御量は下限の観測値で、とどめの証拠にはしない。ブロックされた探索候補も `tactics_forecast.candidates` に残る。

```json
{"normal_tactics":{"pressure":{"enabled":true,"min_remaining":28,"block_seed_chain":9},"finish":{"enabled":true},"counter_read":{"depth":3,"max_nodes":8000}}}
```

控えめな要求の例は `min_remaining=32, min_heights=[4,4,4,3,3,3], max_chain=2, min_send=6, max_send=30, max_main_loss=0, max_attacks=1, allow_pending=false, preempt=false`。強引な例は `min_remaining=8, min_heights=[0,0,0,0,0,0], max_chain=5, min_send=1, max_send=180, max_redundancy=24, max_main_loss=8, max_attacks=3, allow_pending=true, preempt=true, race_margin_frames=60, min_enemy_points=2100, preempt_bonus=18, counter_cost_weight=2, gauge_weight=12, gauge_gain_weight=2, surplus_weight=2`。どちらも `enabled=true` とし、`attacks_used` は実行済み回数を渡す。例は対戦未調整で、勝率改善を確認した設定ではない。強引な値でも生存・必要防御の優先と `block_seed_chain` は迂回しない。

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

既定では通常相手にはゲージ増加へ一般加点せず、双方未突入なら自分の突入を避け、本線を残す副砲で相手の突入を促す。相手の実Fever経験後は合戦の返しへ切り替える。十分な本線返し同士は実得点優先、同点なら短時間。推定kill比率だけで構築を上書きせず、互換の `projected_kill` は0。

全消し目的の加点は開始8手以内・Fever未経験・観測最大4未満、消す色ぷよ16以下・3連鎖以下に限る。全消しの実効果、必要相殺、構築の発火を禁止する条件ではない。

相手Feverへの攻撃は [FEVER_DISRUPTION.md](FEVER_DISRUPTION.md)。`finish_probe` は可視経路と全端数列で救済の有無を検査し、逃げがなければ最短決着を選ぶ。出現列が塞がる場合は観測した現在姿勢が必要。

## Feverのタネ探索

実盤面・可視3ツモの配置列を探索し、最初に消した所でタネ交換として打ち切る。規定未満の掃除でも交換し、同じタネの掃除後を継続しない。

`seed_options.depth` が可視の手数より大きいときは、通常の構築（`fever::search_multi`）と同じ6つの仮想列（形はキャラの周期と `dropset_index`、色は固定の色袋）で、その深さまで同じ探索を行う。根の手は、6列での最悪の区分、次に期待点の合計で順位を付け、返す手順は可視の範囲で切る（`virtual_values`、`virtual_line_truncated`）。`width` は各段に残す局面数、`max_nodes` 0 はノード上限なし。`depth` を省くと可視3手だけを読む。用意した答えがない判断（`cold_spawn`）では、通常の構築と同じく幅を50以下にし、深さは変えない。実機用にこのPCのCPU向けで速くビルドするときは `tools/build_fever_native.ps1`（返答は `build.ps1` と同じ。別のPCではビルドし直す）。

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

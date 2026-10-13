# Observation-based operation API (2026-10-09)

`core/operation.*` owns current-pose rotation and shortest operation routes.
`build.ps1` builds `operations.dll` beside the selected output executable.
The bridge calls the versioned cdecl ABI directly, without waiting for the
placement-search process. Each edge returns input, resulting x/y/r, quick-turn
arming, and nominal input duration (3 frames, or 9 for a sideways kick).
The bridge observes each result. Fever step execution plans once and drops at
the observed position on a mismatch; it does not request a replacement route.
There is no Python/archive fallback when the library is absent or incompatible.

Coordinates: x=0..5, y=0 at the visible top, floor y=11. ABI 1 reports rule 0
for Tsu and rule 1 for Fever. Tsu accepts pairs only. Fever also accepts triples,
quads and big puyos; quads/big never kick or climb. The two-edge quick turn is
restricted to pairs. Triple push-back is experimental and needs Steam validation.
Tsu pair rules retain the pivot ceiling at row 13. The shared base follows main; Fever-specific extensions stay on the Fever
branch and are not ported into Tsu.

Fever `special_moves` enables pair/triple placement candidates proven reachable
by this model, including kicks and quick turns. Default solo protocol behavior
is preserved unless this flag is supplied; the live bridge and battle worker
enable it for this trial. Field scoring, timing and Tsu/Fever death rules stay
separate. This verifies a model, not the game's Fever rotation mechanics.

Fever placement evaluation has no special-operation penalty. Nominal frames
are for input scheduling/observation only. The ABI can disable kicks explicitly
for legacy no-kick simulator tests; live sessions enable them by default.

## 2026-10-09 Fever固有の壁越え・2個組消去

ユーザー指示に従いmain (dea210b) の左右移動、回転時の押し戻し、床蹴り、クイックターンを基礎とする。資料の操作列を固定マクロにせず、現在位置を頂点とする操作探索が必要な入力を選ぶ。通用の処理・軸の13段上限は維持する。

- Feverの出現高さで横を押しながら回す操作を独立した辺として追加。12段目の上へ子を引っ掛けるので11段の足場は不要。通常の移動・回転と交換可能な同時入力とは区別する。落下してこの高さを過ぎた観測位置からは、この辺を使えない。
- 3個組の引っ掛けは左側で左1回、右側で左3回 (U,L,D,R)。L/Jは色配置が異なる同一形状として扱う。高段で同じ長さの経路がある場合は左回転を先に探索し、通常盤面の探索順はmain由来のまま保つ。回転ごとに離す入力を挟む。
- 2個組だけは軸を14段目まで浮かせ、子を15段目に置ける。5列目12段＋6列目13段、または2列目12段＋1列目13段を使う昇竜から外側の縦置きへ到達できる。既存のFever drop_pieceが14・15段目の2個をdiscarded=2として捨て、盤面を変えない。13段目は保持し、捨てた14段目の障害物は残さない。3個組の軸上限と4個組/でかぷよの蹴り禁止は拡張しない。
- bridgeはAmaの各辺の入力と予想姿勢を実行・観測する。引っ掛けの先行入力は横＋回転、DOWNなし。通常直行処理は上昇経路を上書きしない。上昇中はDOWNとまとめ押しを止め、横＋回転の特殊辺は回転を離しても横を結果観測まで保持する。
- 特殊操作そのものへの評価ペナルティは追加しない。入力フレーム数は経路の時間見積もりであり、配置評価の減点ではない。ABI 1の構造体は維持し、経路バッファは拡張した状態空間を収容する。

資料: [壁越え・直接画面外設置](https://www.ne.jp/asahi/root/inoue/p16_103c.htm)、[壁越え](https://w.atwiki.jp/puyowords/pages/195.html)、[14段目に置く操作](https://alg-d.com/game/puyo/chain19.html)、[フィールドと2個組無限消去](https://www.ne.jp/asahi/root/inoue/104.htm)。これらの過去作品の説明とユーザー指定を操作モデルに反映したもので、Steam実機の入力時間や成功率は未検証。


### 2026-10-09 消去設置条件・移動のみの先行入力への訂正

2個組の全廃棄候補・経路の終端は、1列目13段＋2列目12段で1列目へ子が上の縦置き、または5列目12段＋6列目13段で6列目へ子が上の縦置きに限定する（軸14段、子15段）。端の隣が11段の場合や横置きの全廃棄、右の段差から浮いて左へ横断する全廃棄は許可しない。placement_allowedを候補生成・経路終端の共通条件とした。例1/3の左廃棄を排除し、例3の右廃棄は維持する。

引っ掛けは出現高さで隣の12段へ回転だけで上がる辺とし、横移動＋回転を合成しない。例2は左移動1回→左回転1回。3個組は左回転1回／右への左回転3回を維持する。main由来の押し戻し・床蹴り・クイックターンを維持し、両側が詰まった2個組では引っ掛けより既存クイックターンの入力判定を優先する。経路終端の姿勢も衝突検査する。Tsuの操作合成・候補・評価には変更しない。特殊操作への評価減点は追加しない。

bridgeは先行入力をAmaの経路の先頭の純粋な横移動だけにする。出現後の移動を観測してから回転し、回転中はDOWNを止めて13段目に置ける高さを保つ。移動・回転が交互になる経路や上昇はAmaの一手ごとの姿勢を観測し、経路全体を確認してからDOWN。従来の横＋回転先行入力の説明はこの仕様に置き換える。

- 2026-10-09 追加依頼：3個組のシビアな回転時機を通の迅速な操作に合わせる。bridgeのAma経路実行はautoplayの2フレーム押下・1フレーム解放をゲームカウンタで管理し、押下中も姿勢を観測する。最後の姿勢が確認できたら解放待ちを省いて落下する。カウンタなしは時間で代替し、停止しても有限時間で返す。モデルの通常600通り・欠落試験の失敗数を維持。実機改善は未確認。Amaの操作グラフとDLLはこの追加修正で変更していない。


### 壁越え終端の同時操作の訂正

ユーザーの操作例に合わせ、2個組が12段の壁の上へ横向きに乗った姿勢から、回転＋外向き横移動を一つのAma操作として追加した。左へ越えて子を上にする場合は左回転→左移動→右回転＋左移動、子を下にする場合は最後を左回転＋左移動にする。5列目の壁を越えて6列目へ置く場合は左右反転（右回転→右移動→左／右回転＋右移動）。出現位置から壁の手前までの横移動は通常のAma経路を使う。

先行入力の制限は変更しない。通常操作の並行入力など、この修正前に追加された別の変更は維持する。例外の同時辺はFeverの2個組・12段の壁・軸13段・外向き横向きに限定し、縦向きの終点は衝突検査する。必要なら1段上昇を許す。3個組や通の操作にはこの辺を追加しない。特殊操作の評価減点はない。reachableとrouteに同じ辺を入れ、bridgeは高さが変わらなくても同時辺を特殊操作として単独実行し、横入力を予測姿勢の観測まで保持する。従来のFeverの同時操作全面禁止はこの壁越え終端に限り訂正する。

ログのAI1ツモ52・AI2ツモ28の盤面と左右反転、子が上／下の計8経路で指定の3入力を確認。実行側も独立した人間の操作例の観測姿勢を使う入力試験で左右・上下4通りを再生し、同時入力と解放を確認した。これは操作例との一致を確認するもので、Steam実機の成功率検証ではない。

Fever triple hook requires the pivot approach column to have at most 10 rows. The logged 11-row approach pushes away through the ordinary kick; it must not use the 12-row hook. This restriction applies only to triples.

## 2026-10-13 作業A：14段目からの横移動中の自然落下

Feverの2個組で、軸が14段目（y=-2）に上がった後に足場を離れて横移動する経路へ、自然落下の位相を追加した。配置候補の `reachable` と操作DLLの `route` が同じ遷移を使う。1段24フレーム、横移動1列5フレーム（bridgeの `bring` に記載されたタップ移動の見積もり）で、足場のある姿勢では落下を止める。持ち上げの完了は従来どおり整数高さから始める。

少しでも14段目から落ちた姿勢は、衝突検査とABIの期待高さに切り上げた占有段を使う。たとえば -1.77 は -1 であり、-2の余裕を必要とする13段の列には移れない。途中で失った高さを未測定の空中蹴りで取り戻す経路も生成しない。空いた列への移動は残し、実行側に落下分を見込んだ期待高さを返す。照合条件の緩和、操作開始後の再計画、出現後の配置差し替えは追加しない。

今回の時計は横移動で足場を離れた時点から数える。13段目以下の操作、静止中の14段目回転・持ち上げ、3個組は既存のモデルを維持する。これらの実機不一致は別件であり、全操作の時間校正ではない。5フレームは保持入力や全入力位相を保証する測定値ではなく、今回の経路検査の保守的な見積もり。

再現例：高さ `[13,13,9,7,11,12]`、2個組の目標 `(2,L)` は、従来の「右端で浮かせる→左3列→左向きへ回転」では届かない。候補から外す。壁越え、端の12段足場を使う2個組廃棄、13段の足場に載ったままの横移動は回帰で維持する。Tsuの遷移・ABI 1・構造体の公開レイアウトは維持する。

検証状況と実機受入れの残件は `doc/WORK_LOG.md` の作業Aの追記を参照。オフラインの旧ログ照合は新AIの対局結果を予測するものではない。

### 同日追加：構築中の経路再探索を削減

最初の作業A版は実戦で2Pの判断待ちを増やした。2個組の配置生成はすでに `reachable` で判定しているのに、`normal_space::moves` が同じ盤面で24目標の `route` をもう一度実行していた。落下位相の拡張後はこの重複が高価になった。2個組は生成済み候補を使い、生成側だけにある実測拡張を除外する3個組のフィルターは維持する。

Feverの2個組・出現姿勢 `(2,0,U)` からの到達判定は6列の高さだけで決まるため、結果をスレッドごとの2048枠に保持する。高さ全体のキーを照合して再利用し、別の開始姿勢・3個組・Tsuでは使わない。落下遷移と操作DLLの経路の選び方は変更していない。

実ログ9盤面の単体比較で容量判定・構築・配置の返答は一致し、別の542盤面・ツモでも配置の返答は一致。判断待ちを含む実機速度の受入れは更新版の再起動後に確認する。測定の詳細は `doc/WORK_LOG.md` 続き30。

## 2026-10-14 失敗した3個組の特殊回転を一時停止

ユーザー依頼により、3個組の12段の列への引っ掛けと、出現高さ以上で12段以上の列に当たった回転の横への押し戻しを一時停止した。左右反転も同じ種類として扱う。2個組・通常回転・盤面の端だけに当たる押し戻し・低い位置の床蹴りは維持する。

`fever/operation_suspensions.h` の2つのフラグをfalseとし、`rotate`／`hook` の辺を候補生成とDLLの両方から外す。経路を確認できない生成側だけの `measured_triple` 拡張も一時停止して、ソロ構築の迂回を防ぐ。停止した辺を使わない経路で届く配置は維持する。

失敗5例の盤面・ツモ・手順・予測・フレームごとの実測と、修復／再有効化の確認点は [一時無効化した3個組の操作](../doc/DISABLED_TRIPLE_OPERATIONS.md) にまとめた。実機の停止後の操作成功率と構築品質は再起動後に確認する。

同日追記：ユーザーの就寝中のログ収集のため、3個組の引っ掛けと高段横押し戻し、生成側だけの拡張を一時的に再有効化する。これらの修復は未実施。2個組の作業Aの落下検査と速度修正は維持する。収集後の再封印は `operation_suspensions.h` の2フラグをfalseへ戻す。

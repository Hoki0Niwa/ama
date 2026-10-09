# Observation-based operation API (2026-10-09)

`core/operation.*` owns current-pose rotation and shortest operation routes.
`build.ps1` builds `operations.dll` beside the selected output executable.
The bridge calls the versioned cdecl ABI directly, without waiting for the
placement-search process. Each edge returns input, resulting x/y/r, quick-turn
arming, and nominal input duration (3 frames, or 9 for a sideways kick).
The bridge observes each result and requests a new route on a mismatch.
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

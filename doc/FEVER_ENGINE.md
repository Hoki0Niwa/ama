# 単独構築エンジンと計測

単独構築用のAPI。ゲージ・時計・相手を含む対戦判断は [FEVER_MODE_ENGINE.md](FEVER_MODE_ENGINE.md) を参照する。`bench_fever` の色列・仮コストをSteamの実測や勝率に読み替えない。

## 1. ファイル構成

| ファイル | 内容 |
| --- | --- |
| `core/fever_queue.*` | 試作用の色列生成器と、探索用の仮想列 |
| `fever/search.*` | `Piece` 対応のビーム探索。既存の `beam::Layer`・置換表・評価関数を使う |
| `fever/fire.*` | 連鎖数で判定する発火方針と、1手を決める `fever::think` |
| `fever/text.h` | ツモ・盤面・回転の文字列表現 |
| `fever/main.cpp` | フィーバー用エンジン `bin/fever/fever.exe` |
| `bench_fever/main.cpp` | 一括計測 `bin/bench_fever/bench_fever.exe` |
| `bench_fever/sweep.py` | 複数の設定で `bench_fever` を回して1行ずつ要約する |

## 2. 色列

**Steam版の色生成は再現していない。** 試作用モデルは次のとおり。

- 乱数は splitmix64。状態はシードそのもの。色1つにつき1回引き、上位2ビットを色（0赤・1黄・2緑・3青）にする。4色の独立一様乱数。
- 2個組：軸、子の順に2色。同色あり。
- 3個組：A、Bの順に2色。`L`（縦）は `(A,A,B)`、`J`（横）は `(A,B,A)`。B=Aなら同色3個組。
- 2色4個組：Aを引き、BはA以外の3色から一様に1回で引く。初期配置は左列A・右列B。
- でかぷよ：1色。置く色は配置の `r` で選ぶので、この色は表示上の初期色にすぎない。
- 初手の色数制限、Steam版の置換規則はない。旧表記 `3`（向き不明の3個組）と `unknown` の周期は `std::nullopt` で、推測しない。

`fever::create_queue(character, seed, count, start)` は周期の `start` 手目から `count` 個を返す。同じ引数なら同じ列で、`count` を変えても先頭は変わらない。

探索用の仮想列 `fever::create_queue_virtual(character, id, count, start)` は乱数を使わない。形状は周期から取り、色は既存の `beam::get_queue_random` と同じ6本の色袋（4色の順列）を、ツモの色スロットへ順に2色ずつ配る。でかぷよは袋から取らない。袋の隣り合う2色は必ず異なるので、仮想列に同色2個組・同色3個組は現れず、2色4個組の制約も満たす。アルル（全16手が2個組）の仮想列は通の仮想列と同じになる。

実際の色列と仮想列は別の仕組みで、状態を共有しない。探索へ渡すのは見えているツモだけ。

## 3. 探索

`fever::search_multi(field, queue, character, index, weights, configs)`

- `queue` は見えているツモ（現在手＋NEXT2）、`index` は `queue[0]` が周期の何手目か（0始まり）。深さの残りは6本の仮想列で埋め、6スレッドで探索して候補ごとに結果を合算する。
- 子ノードは `move::generate` → `drop_piece` → `pop` → `is_dead(rule::FEVER)`。ちぎりコストは `DropResult::split`。地形評価・静止探索・置換表は通の基盤を使い、Feverの重みは `config.json` の `fever`（なければ `build`）。
- 同じ層のノードは周期の同じ手にあるので、置換表のハッシュは盤面だけで足りる。周期位置は含めていない。
- 枝刈りは連鎖数：5連鎖以上を発火した子は展開しない（`PRUNE_CHAIN`）。早期終了も連鎖数（`Configs::trigger`、既定14）。
- 現在手をすべて捨てて盤面が変わらない配置は、行動コストが同じなら後続の探索を共有する。配置別の予測には共有した値を返し、回転違いの配置も実行候補に残る。
- 候補の順位は、各仮想列の連鎖評価を合算する。`construction_scoring` の通常構築ではキャラ別通常倍率とFeverの色・連結ボーナスを使う。候補には最長連鎖数 `chain` も持たせる。
- 静止探索の到達範囲（`quiet::get_bound`）は3列目から左右へ12段未満の列をたどる。フィーバーで生存している盤面は3・4列目とも12段未満なので、そのまま使える。

単独APIと対戦エンジンから呼ぶ通常構築では、試作の `fever.stack_balance` で片側の高積みを抑える。左右3列ずつの高さの合計差が6個を超えた分と、最高列が盤面の平均より3段を超えて高くなった分を減点する。最高列の減点は、その列を中央へ移しても同じ高さなら残る。減点は盤面を左右反転しても同じで、構築ビームが評価する消去後の盤面ごとに、占有数12個までは全量、そこから `stack_balance_end_cells`（既定40）まで線形に弱める。終了の占有数以上で減点は0になる。重みは整数で0〜1000に制限し、省略または0で無効になる。

ランチャーではフィーバーの「長連鎖探索」にある「左右差を小さくする」で重みを設定する。旧プリセットの `hill` は取り除かれ、新しい重みは保存済みの `stack_balance` がなければ0になる。

発火方針 `fever::fire::decide` は連鎖数で判定する。通の `ai::fire` が手持ちの1手だけを見るのに対し、**見えている全ツモ（最大3手）で撃てる最長連鎖**を全探索で求める（`fire::best_visible`）。色が確定しているので正確な値で、仮想列の楽観に左右されない。条件を満たすと、その連鎖へ向かう1手目を返す（`fire_moves` は発火までの手数）。

- その連鎖が `trigger`（既定14）以上なら発火。
- 盤面が `panic_count`（既定70）個以上で、`panic_chain`（既定11）連鎖以上なら発火。
- `panic_step`（既定0＝無効）：盤面が埋まるほど必要連鎖数を1つずつ下げる。
- `shave_chain`（既定0＝無効）：探索の手が小連鎖で盤面を削ろうとするとき、見えるツモでこの連鎖数以上を撃てるならそちらを撃つ。

発火方針の既定値は単独APIと対戦で異なる。対戦は `battle_policy.json` と要求を基に設定する。

`fever::think` が探索と発火方針をまとめ、エンジンと `bench_fever` の両方がこれを呼ぶ。

でかぷよは、隣り合う2列の高さの差が1以下なら4個がつながって即座に消える（1連鎖）。差が2以上でちぎれれば残る。現状の評価はこれを特別扱いしていない。

## 4. エンジンのプロトコル

```
bin/fever/fever.exe [config.json]
```

標準入力から1行1リクエストのJSONを読み、1行1返答を返す。`config.json` に `fever` があればその重み、なければ `build` を使う。Tsu用の `pvp.exe --engine` とは別のバイナリ・別の形式で、`"rule": "fever"` のないリクエストは拒否する。

```json
{"rule": "fever", "character": "raffina", "dropset_index": 0, "solo": true,
 "self": {"field": ["......", "...14行..."], "queue": ["2:RG", "2:BY", "L:RRG"]},
 "trigger": 13, "stretch": true, "beam_width": 250, "beam_depth": 16,
 "fire": false, "include_next": false}
```

| フィールド | 意味 |
| --- | --- |
| `rule` | `"fever"` 必須 |
| `character` | `dropsets.json` の `id` |
| `dropset_index` | `queue[0]` が周期の何手目か（0始まり、16で循環） |
| `solo` | `true` 必須。単独用の要求 |
| `self.field` | 14行、先頭が14段目。文字は `RYGB#.`。浮いたセルは拒否。14段目の行は無視する |
| `self.queue` | 見えているツモ。全て周期の形状と一致しなければ拒否 |
| `trigger` | 発火する連鎖数（既定14） |
| `maximize_score` | `true` で目標連鎖数による探索打ち切りを無効にし、通常発火をキャラ別得点で判断する |
| `score_rebuild` | 得点最大化時の盤面整理。既定は無効。明示的に `true` を指定すると有効。単独要求では直近の消去以降の手数を `moves` に渡す |
| `panic_count`, `panic_chain`, `panic_step`, `shave_chain` | 発火方針の設定（第3節）。省略時は既定値 |
| `fire` | `true` なら、今すぐ撃てる最長連鎖の配置を返す |
| `include_next` | 配置後の盤面と連鎖を返す |

得点最大化では、通のDFSと同じ考え方で、見えている最初の1〜2手を実際に置いた形に発火用の色ぷよを仮置きし、形状評価で選んだ連鎖の得点を構築候補ごとに比較する。発火候補には現在手からNEXT2までで実行できる最高得点を使う。通常の発火ラインはキャラ別の標準 `score_fire_chain` 連鎖（各段4個消し、既定14）の得点。可視の最高得点が発火ラインに届くか、`score_reserve_chain` 連鎖（既定12）以上かつキャラ別の同じ連鎖数の標準得点に達する場合は、同等以上の得点を可視ツモで維持できる構築手に絞る。別の構築手にその経路がなければ、途中の小消しを含めて可視の発火手順を選ぶ。対戦エンジンが初回本線の下限を渡した場合は、その連鎖数を満たす可視経路を優先する。`score_reserve_chain` 連鎖から下限未満までは、発火手で積み手がなくなることが可視ツモから分かる場合に経路を保持する。すぐ発火できる場合は、可視ツモを切り捨てずに積める経路があれば構築を続ける。経路を保持する局面では `visible_fire_protected` を返す。可視の得点がこの条件に届かない間は、盤面の余裕と6仮想列の得点予測を使い、構築の続行、発火、盤面整理を比較する。返答の `fire_line_points` は発火ライン、`repair_line_points` は修復・盤面整理の比較に使う標準14連鎖の得点、`build_potential_points` は発火と構築を比較した場合の構築側の最高予測点。

得点最大化の[盤面整理](FEVER_CAPACITY_CONVERSION.md)を採用した返答には `score_rebuild` があり、消去前後の総数と、通常構築・整理後の6仮想列の目標点到達数を返す。

ツモ文字列は `形状:色`。色の順は `piece::Piece::colors` と同じ。

| 文字列 | 形状 | 色の順 |
| --- | --- | --- |
| `2:RG` | 2個組 | 軸、子 |
| `L:RRG` | 縦3個組 | 軸、上、右（軸＝上） |
| `J:RGR` | 横3個組 | 軸、上、右（軸＝右） |
| `4:RRGG` | 2色4個組 | 左下、左上、右下、右上 |
| `0:R` | でかぷよ | 表示中の1色 |

同色3個組は `L:RRR` でも `J:RRR` でもよいが、周期の L/J と一致させる。

返答：

```json
{"x": 2, "r": "U", "shape": "2", "chain": 0, "eval": 0, "fire": false, "solo": true, "search_ms": 12.3}
```

- `x`：2個組は軸の列、他は2×2の外接枠の左列（0〜4）。
- `r`：時計回りの回転数を `U`/`R`/`D`/`L`（0〜3回）で表す。でかぷよは色の添字で、`U`赤・`R`黄・`D`緑・`L`青。`color` に同じ色を文字でも返す。
- `chain`：探索が見込む連鎖数。`fire` が真なら今撃つ連鎖数。`eval`：仮想列での平均点、または今撃つ点数（採用した得点モデル）。
- `fire`：発火方針が選んだ手か。真なら `fire_moves` に、その連鎖が発火するまでの手数（この手で発火するなら1）を返す。
- `include_next` 時：`next_field`、`next_chain`、`next_score`、`next_discarded`（14段目以上で消えた個数）、`next_all_clear`。
- 失敗時は `{"error": "..."}` だけを返し、プロセスは続く。

実行経路は [操作API](../docs/OPERATIONS.md) を参照する。

## 5. 計測：`bench_fever`

```
bin/bench_fever/bench_fever.exe <weight.json> <character> <seed_begin> <seed_end> <out.tsv> [max_moves=100] [snapshot.txt] [moves.jsonl]
```

環境変数：`BEAM_WIDTH`、`BEAM_DEPTH`、`BEAM_TRIGGER`（連鎖数）、`PANIC_COUNT`、`PANIC_CHAIN`、`PANIC_STEP`、`SHAVE_CHAIN`、`BENCH_GOAL`（終了する連鎖数、既定10）、`QUEUE_VISIBLE`（1〜3、既定3）。

1シード1ゲーム。`BENCH_GOAL` 連鎖以上を発火したら `fired` で終了。ほかは `dead`、`nomove`、`timeout`（手数切れ）。TSVの列：

| 列 | 内容 |
| --- | --- |
| character, seed, result | |
| score | 目標に達した連鎖の点数（採用した得点モデル）。なければ0 |
| max_score, max_count | 最長連鎖の点数と連鎖数 |
| moves, frames | 手数と、探索の仮コスト（設置1・ちぎり+1・連鎖数×2）。実フレームではない |
| ms, ms_max | ゲーム全体の実時間と、1手の最長思考時間 |
| cells, discarded | 投入したぷよ数と、14段目以上で消えた個数 |
| small | 1〜3連鎖を発火した回数 |

`snapshot.txt` は `bench/render.py` がそのまま読める（最後の発火直前の盤面）。`moves.jsonl` は1手1行で、ツモ・配置・連鎖・設置直後の盤面 `placed`・連鎖後の盤面 `field` を持つ。puyop のURLは特殊ツモを表せないので出さない。

設定の比較は `bench_fever/sweep.py` で行う。

```
python bench_fever/sweep.py -o bin/fever-sweep --seeds 1001-1040 --jobs 3 base t15:trigger=15 tear:tear=-100
```

`名前:キー=値,...` の形で、キーは重み（`config.json` の `fever`、なければ `build` が基準）か、`width`・`depth`・`trigger`・`goal`・`visible`・`panic_count`・`panic_chain`・`panic_step`・`shave`。設定ごとに TSV・スナップショット・手のログを出し、平均最大連鎖数、10〜15連鎖以上の率、死亡・未発火の数、手数、小連鎖の回数、1手の時間を1行で表示する。全シードが済んだ設定は再実行しない。並列に回すと1手の時間は参考値になる。

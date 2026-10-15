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
- 候補の順位は、各仮想列の連鎖評価を合算する。`construction_scoring` の通常構築ではキャラ別通常倍率とFeverの色・連結ボーナスを使う。候補には最長連鎖数 `chain` も持たせる。
- 静止探索の到達範囲（`quiet::get_bound`）は3列目から左右へ12段未満の列をたどる。フィーバーで生存している盤面は3・4列目とも12段未満なので、そのまま使える。

発火方針 `fever::fire::decide` は連鎖数で判定する。通の `ai::fire` が手持ちの1手だけを見るのに対し、**見えている全ツモ（最大3手）で撃てる最長連鎖**を全探索で求める（`fire::best_visible`）。色が確定しているので正確な値で、仮想列の楽観に左右されない。条件を満たすと、その連鎖へ向かう1手目を返す（`fire_moves` は発火までの手数）。

- その連鎖が `trigger`（既定14）以上なら発火。
- 盤面が `panic_count`（既定70）個以上で、`panic_chain`（既定11）連鎖以上なら発火。
- `panic_step`（既定0＝無効）：盤面が埋まるほど必要連鎖数を1つずつ下げる。
- `shave_chain`（既定0＝無効）：探索の手が小連鎖で盤面を削ろうとするとき、見えるツモでこの連鎖数以上を撃てるならそちらを撃つ。

発火方針の既定値は単独APIと対戦で異なる。対戦は `battle_policy.json` と要求を基に設定する。

`fever::think` が探索と発火方針をまとめ、エンジンと `bench_fever` の両方がこれを呼ぶ。

でかぷよは平らな場所に置くと4個がつながって即座に消える（1連鎖）。段差に置いてちぎれば残る。現状の評価はこれを特別扱いしていない。

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
| `panic_count`, `panic_chain`, `panic_step`, `shave_chain` | 発火方針の設定（第3節）。省略時は既定値 |
| `fire` | `true` なら、今すぐ撃てる最長連鎖の配置を返す |
| `include_next` | 配置後の盤面と連鎖を返す |

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

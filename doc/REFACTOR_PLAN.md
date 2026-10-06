# リポジトリ全体のリファクタリング計画

作成：2026-10-06。状態（2026-10-07）：**R0・R1の基準固定・R2・R4、R3の一部、探索の再編（P2〜P5とP6の一部、SEARCH_PLAN第10節）、R5、R6の一部（第9節）を実施済み。** R7〜R9（ビルド・設定・文書）は未着手。実機での確認はしていない。 探索と評価の再編は [SEARCH_PLAN.md](SEARCH_PLAN.md) に分けてあり、本書はそれを含むリポジトリ全体の範囲・順序・規則を定める。

依頼（2026-10-06）：順序4（代表キャラの実機受入れ）は完了といってよい状態。リファクタリングは後付け実装だけでなく、リポジトリ全体を対象にする。

調査の範囲：`fever_battle/`・`fever/` と `ai/search/beam` の評価部は読んだ。`core/`・`ai/` のその他・`pvp/`・`bench/`・`tuner/`・`puyop/` は行数・関数一覧・ブランチ間の差分を見ただけで、中身を精査していない。精査していない領域の作業内容は、R0の調査で確定する。

## 1. 規則

1. **挙動を変えない変更と変える変更を、別のコミットにする。** 前者は記録再生と固定シードの出力一致で確認し、後者は変わった局面を記録する。
2. **ブランチの分離を守る。** `AGENTS.md` のとおり、Tsuと共有するコードの変更は `irregular-form` で先に行い、`fever` へ一方向に取り込む。
3. **Tsuの挙動を固定する。** 共有コードの変更ごとに `python test/test_engine_protocol.py` と `bench` の同一シード結果の一致を確認する。
4. **置き換え先が検証を通るまで、古い実装を消さない。**
5. **実装・ビルド・自動検証・実機確認を区別して記録する。**
6. **意図した制約は削除しない。** 可視ツモだけを使う、実落下後に再観測する、未観測値を0で埋めない、など（[SEARCH_PLAN.md](SEARCH_PLAN.md) 第4節「残すもの」）。

## 2. 領域と作業場所

| 領域 | 対象 | 作業ブランチ |
| --- | --- | --- |
| フィーバー専用 | `fever/`、`fever_battle/`、`bench_fever/`、`core/piece*`・`dropset.*`・`fever_queue.*`、`test/*fever*`、`tools/`、`data/fever/`、`doc/` | `fever` |
| 共有エンジン | `core/` のその他、`ai/`、`pvp/`、`bench/`、`tuner/`、`puyop/`、`test/main.cpp`、`makefile`、`build.ps1`、`config.json` | `irregular-form` で実施し `fever` へ取り込む |
| 対象外 | `lib/`（外部ライブラリ）、`main` ブランチ | 変更しない |

共有エンジンのうち `fever` と `irregular-form` で既に差がある既存ファイルは33個（`ai/fire.cpp`、`ai/search/beam/quiet.cpp`、`core/field.*`、`core/fieldbit.*` など）。これらを先に `irregular-form` と揃えるかどうかを R0 で調べる。

## 3. 領域ごとの課題

### R1 検証の土台

- 記録再生が機能ごとの別スクリプト（`tools/verify_*`・`replay_*` が9本）と別形式の基準JSON（`data/fever/baselines/` に日付つきで多数）に分かれている。入力と期待出力を1形式にそろえ、1コマンドで全件を再生して差分を出す仕組みにする。
- `test/test_fever_mode.py` は1127行。機能追加の日ごとにテストファイルが増えている（`test_fever_tactics`・`deadlines`・`final_failure`・`garbage_repair` など）。対象モジュール単位へ並べ直す。
- すべての後続作業の安全網になるので最初に行う。[SEARCH_PLAN.md](SEARCH_PLAN.md) のP0を含む。

### R2 フィーバー対戦のnative（`fever_battle/*.cpp`）

- 遷移の重複の集約、JSON文字列キーの置き換え（[SEARCH_PLAN.md](SEARCH_PLAN.md) 第4節B・C、段階P1）。
- 入力検査の関数が4つ重複している（`number` が3ファイル、`bounded_integer` が `main.cpp`）。
- `main.cpp` の `answer` に `finish_probe` の本体（約95行）が直接書かれている。操作ごとの関数へ分ける。

### R3 PythonとnativeとJSONの境界

- 判断がPythonとC++に分かれ、同じ計算を両方が持つ（`uncertainty.py` は相殺・相手イベント・端数列をPythonで再実装。`gauge_wait.py` はnativeの結果からゲージを再計算）。
- `ModeBattleEngine` は protocol 2 用の `BattleEngine` を継承し、検査を使い回すためにモードとゲージを偽った複製（`normal_view`）を渡している。
- `model.py` に入力検査・得点・審判が同居している。
- 方針：**判断（探索・評価・順位）はnativeへ、Pythonはプロトコルの検査・審判・校正・計測に限る。** protocol 2 と 3 の検査は継承ではなく共通の検査関数にする。

### R4 プロセス構成

- 対戦時、Pythonが `fever.exe`（構築）と `fever_battle.exe`（戦術）の2つを別プロセスで呼ぶ。構築の評価を戦術探索の葉から使う（[SEARCH_PLAN.md](SEARCH_PLAN.md) 3.2・3.5）には、同じバイナリから呼べる必要がある。
- 方針：構築探索をライブラリとして `fever_battle` からも呼べるようにする。単独用の `bin/fever/fever.exe` とそのプロトコルは残す。

### R5 フィーバー単独エンジン（`fever/`）とTsu側の重複

- 発火方針が `ai/fire.cpp`（154行）と `fever/fire.cpp`（206行）に分かれている。共通にできる部分があるかを調べる。
- 盤面と文字列の変換が `pvp/main.cpp`（`field_to_rows` など）と `fever/text.h` の両方にある。
- 共通化する場合は、ルールに依存しない形で `irregular-form` に先に入れる。

### R6 共有エンジン（`core/`・`ai/`・`pvp/` ほか）

- `pvp/main.cpp` は1155行で、設定読込・JSON変換・エンジン・子プロセス管理・対戦進行が1ファイルにある。`ai/ai.cpp` は1055行、`ai/path.cpp` は883行。
- 中身は未精査。R0の調査で、分割・重複・未使用コードを一覧にしてから作業を決める。
- 元リポジトリ（citrus610/ama）由来のファイルを大きく組み替えると、以後の取り込みが難しくなる。どこまで組み替えるかは決定が要る（第5節）。

### R7 ビルドと成果物

- `build.ps1` は9ターゲット、`makefile` は5ターゲットで、フィーバー系は `build.ps1` にしかない。対象ソースの列挙は `build.ps1` 内の条件分岐に手書きされている。ターゲットとソースの対応を1か所にまとめる。
- `bin/` に検証用の退避先（`t6`〜`t22` など約30個）があり、ソースの複製（`bin/t15/before-*.cpp`）も含む。Git管理外。作業記録がSHA256で参照しているものがあるため、削除はユーザーの確認後に限る。

### R8 設定とデータ

- 方針・規則・時間・得点が `config.json`・`battle_policy.json`・`mode_rules.json`・`timing.json`・`scoring.json` とC++・Pythonの定数に分散している。「実測値」「出典からの転記」「試作のしきい値」を区別したまま、定数をデータ側へ寄せる。
- `data/fever/baselines/` は R1 の形式統一に合わせて整理する。過去の測定記録は消さない。

### R9 文書

- `doc/README.md` の冒頭が日付順の追記の積み重ねになり、現在の状態が読み取りにくい。現状の要約だけにし、経過は `WORK_LOG.md` に任せる。
- 仕様書（`FEVER_MODE_ENGINE.md` など）は追記で前の節を訂正する形が重なっている。現行仕様だけを述べる形へ書き直し、訂正の経緯は `WORK_LOG.md` に残す。
- `doc/` と `docs/` の2つがある。`docs/` は1ファイルだけ。
- `WORK_LOG.md`（約2000行）は履歴として残し、書き換えない。

## 4. 作業順序

| 段階 | 作業 | 領域 | 完了条件 |
| --- | --- | --- | --- |
| R0 | 全体調査。未精査の領域を読み、重複・未使用・分割候補を一覧にする。`fever` と `irregular-form` の既存ファイルの差を分類する | 全体 | 本書第3節の各項が、場所つきの作業一覧になる |
| R1 | 検証の土台の統一と基準の固定 | フィーバー専用 | 1コマンドで全記録を再生でき、現行バイナリの出力が基準として残る |
| R2 | フィーバー対戦nativeの整理（SEARCH_PLANのP1を含む） | フィーバー専用 | 再生の出力が基準と一致する。列あふれ規則の統一による差だけを別に記録する |
| R3・R4 | Pythonとnativeの境界、プロセス構成の整理 | フィーバー専用 | 再生の出力が基準と一致する。思考時間が悪化しない |
| 探索の再編 | SEARCH_PLANのP2〜P6（評価の差し替えと後付け実装の削除） | フィーバー専用 | SEARCH_PLAN第5節の各完了条件 |
| R5・R6 | 共有エンジンの整理 | 共有エンジン | `irregular-form` でTsuのプロトコル試験と固定シード結果が一致し、`fever` へ取り込んだ後も一致する |
| R7・R8 | ビルド・設定・データの整理 | 両方 | 全ターゲットがビルドでき、全テストが通る |
| R9 | 文書の整理 | フィーバー専用 | 各文書が現行の状態だけを述べ、経緯は作業記録から辿れる |
| 実機確認 | 整理後のバイナリで実対戦 | — | 対戦ログで入力と判断を確認する |

R1→R2→R3・R4 の順は依存関係がある。R5・R6 は別ブランチの作業で、フィーバー側と並行できる。R9 は各段階の区切りでも進められる。

## 5. 決定事項（2026-10-06ユーザー）

1. **共有エンジンの作業場所**：`irregular-form` で行い、`fever` へ一方向に取り込む。作業場所は別のチェックアウト（`C:\Users\ho_ki\git\ama`）。
2. **Tsuの出力の固定**：共有エンジンの整理では、固定シードの結果を完全に一致させる。
3. **元リポジトリ由来のファイル**：非効率なものは組み替えてよい。`irregular-form` と `fever` の両側に反映する。**`main` ブランチは変更しない。**
4. **判断をnativeへ寄せる**（R3）：行う。
5. **仕様書の書き直し**（R9）：追記の積み重ねを現行仕様へまとめ直す。経緯は `WORK_LOG.md` に残す。
6. **並行作業との区切り**：Codexによる修正を含む作業ツリーをコミット・pushして区切りとした。以後の整理はこのコミットを基準にする。

未決：元リポジトリ由来のファイルで何を「非効率」と判定するかの基準は、R0の調査結果を見て個別に決める。

## 6. R0の調査結果（2026-10-06）

行数・関数一覧・呼び出し関係・ブランチ間の差分・対になる実装の共通行数を機械的に調べた結果。**各ファイルを通読したわけではない。** 共有エンジンの個々の作業は、着手時に該当ファイルを読んで確定する。

### 6.1 ブランチとチェックアウトの状態

- `irregular-form`（`cff22d9`）は `fever` にすべて取り込み済みで、`irregular-form` 側にだけある変更はない。
- 逆に、`fever` には既存の共有ファイル21個への変更があり、`irregular-form` に入っていない。空白と改行を除いた実質の差は次のとおり。
  - 速度改善：`core/fieldbit.cpp` → `fieldbit.h` への移動（135行）、`core/field.*`、`ai/search/beam/quiet.*`（+56/−14）、`table.*`（+27）
  - 1〜2行の差：`ai/fire.cpp`、`beam.cpp`、`eval.cpp`、`form.h`、`dfs/attack.cpp`、`dfs/build.cpp`、`core/move.*`、`bench/`・`puyop/`・`pvp/`・`test/` の `main.cpp`、`tuner/score.h`
  - `ai/fire.cpp` は308行の差として表示されるが、実質は2行で、残りは改行コードの違い。
- **`irregular-form` のチェックアウト（`C:\Users\ho_ki\git\ama`）に未コミットの変更がある。** 19ファイル・+764/−275行と、新規ファイル（`pvp/timing.*`・`pvp/simulator.h`・`test/chain_quality_test.cc` など）。`fever` と同じファイル（`core/field*`・`beam/quiet*`・`table*`・`eval.cpp`・`pvp/main.cpp`）を含む。内容は確認していない。
- 帰結：共有エンジンの整理（R5・R6）の前に、(1) そのチェックアウトの未コミット変更を区切る、(2) `fever` にだけある共有ファイルの変更を `irregular-form` へ戻して両ブランチの共有部分を揃える、の2つが要る。(2) は `AGENTS.md` の一方向マージの例外になるため、チェリーピックではなく `irregular-form` 側で同じ変更を作り直してから `fever` へ取り込む形にする。

### 6.2 共有エンジンの構造

| 場所 | 事実 | 候補 |
| --- | --- | --- |
| `ai/ai.cpp` | 1055行のうち `think` が1関数で約870行（184〜1055行）。防御・速攻・とどめ・牽制・構築の分岐が1つの関数内にある | 判断ごとの関数へ分割。分岐の順序と条件を変えない |
| `pvp/main.cpp` | 1155行に、設定読込、盤面と文字列の変換、JSON変換、エンジン2種（同一プロセス・子プロセス）、対戦進行、表示、`main` がある | プロトコル（JSON変換）・エンジン・対戦進行へ分割 |
| `ai/path.cpp` | 883行。参照元は `pvp/main.cpp` だけ | 配置だけ確認。分割は不要の可能性が高い |
| `ai/search/dfs/` と `beam/` | `eval.cpp` 同士で113行、`quiet.cpp` 同士で51行が同一（空白を除く一意行） | 高さ・連結・形状の評価部品を共通化 |
| `ai/search/beam/beam.cpp` と `fever/search.cpp` | 291行のうち95行が同一。ツモの型（2個組／特殊形状）と展開関数だけが違う | 展開関数を引数に取る形でビーム本体を1つにする。`irregular-form` 側の変更が要る |
| `ai/fire.cpp` と `fever/fire.cpp` | 共通行は15行だけ | 共通化の利得は小さい。対象から外す |
| `bench/main.cpp` と `bench_fever/main.cpp` | 共通行は54行 | 出力・集計部だけ共通化を検討 |
| `fever/text.h` と `pvp/main.cpp` | 盤面・方向と文字列の変換が両方にある | `core/` へ1つにまとめる |

### 6.3 フィーバー専用の構造

- `fever_battle/*.cpp` の入力検査関数は4つ重複（`number` 3つ、`bounded_integer` 1つ）。
- Pythonのテストは20ファイル。うちFever系は `test_fever*.py` の17ファイル・226件（2026-10-06の実行で全件成功）。
- `tools/` の再生・検証スクリプトは9本で、入力形式・比較方法・出力形式がそれぞれ異なる。
- `data/fever/baselines/` の34ファイルのうち、protocol 3 の要求を含むのは6ファイル・計34要求。

### 6.4 R1で追加した検証の土台

- `tools/fever_check.py`：`test`（Fever系テストの一括実行）、`record`（基準の記録）、`replay`（基準との比較）。
  - native基準：テスト実行中に `fever_battle.exe` と `fever.exe` が受けた要求と返答をすべて記録する（`fever_battle/worker.py` に環境変数 `AMA_NATIVE_TRACE` で有効になる記録を追加。未設定時の動作は変わらない）。2回実行して返答が食い違った要求は「不安定」として比較から外す（探索が時間予算で打ち切られる場合）。
  - エンジン基準：`data/fever/baselines/` に保存済みの protocol 3 要求を、毎回新しいエンジンで判断させた返答。
  - 基準は `data/fever/golden/`。比較から外すのは経過時間の項目だけ。
- `tools/bench_fever_baseline.py`：`seed`（公開タネ50個を試作用色列のツモで初回消去まで進め、規定達成率・手数・フレームを数える）、`entry`（通常盤面で構築中に一定間隔で確定予告を足し、ゲージ7までの手数・突入率・死亡を数える）。
- どちらもオフラインのモデル上の値で、実機の成功率・対戦結果ではない。

### 6.5 基準値（2026-10-06、コミット `19848e9` のソース）

対象バイナリ：`bin/fever_battle/fever_battle.exe`（SHA256 `9273efe1…abbd0c`）、`bin/fever/fever.exe`（`9ca69c25…dff25`）。

| 項目 | 値 |
| --- | --- |
| Fever系テスト | 17ファイル・226件成功 |
| native基準 | 2091要求（`fever_battle.exe` 1600、`fever.exe` 491）。2回の実行で全件が同じ返答 |
| エンジン基準 | 34要求中33が安定。1件は2回の返答が食い違い、比較から除外 |
| 再生（現行バイナリ） | 2124件比較・差分0 |
| 再生（1つ前の退避バイナリ `fever_battle.pre-long-extension-20261006.exe`） | 差分509。変更を検出できることの確認 |
| タネ計測（ラフィーナ、時計900F、50タネ×色列2×開始位置3＝300） | 規定達成240（80%）。達成時の平均1.69手・59.4F・規定＋0.08連鎖。全消し54。規定14連鎖は10/24、15連鎖は2/24 |
| 突入計測（ラフィーナ、12手目から3手ごとに確定予告4個、色列12） | 12/12で突入。最初の予告から平均8.83手、突入までの被弾は平均3.08個。最長の思考157ms |

読み方の注意：

- タネ計測のタネは公開資料の盤面を正規化した色で読み込んだもので、ツモは試作用の色列。実機のタネ・色列での成功率ではない。規定14・15連鎖の低さが探索の問題か、ツモの形（でかぷよ等で1手では届かない）によるものかは切り分けていない。
- 突入計測は現行でも全件突入しており、この条件のままでは改善を測れない。P2では予告の量・間隔を厳しくした条件を足して比較する。
- 記録・再生は「以前と同じ返答をするか」を見るもので、返答の良し悪しは示さない。

再実行：

```powershell
python tools/fever_check.py test
python tools/fever_check.py replay
python tools/bench_fever_baseline.py seed --queues 2 --output REPORT.json
python tools/bench_fever_baseline.py entry --queues 12 --output REPORT.json
```

## 7. R2とR1残りの実施結果（2026-10-06）

### 7.1 遷移部品の共通化（挙動を変えない変更、コミット `e1d77c3`）

`fever_battle/transition.h` を新設し、次を1か所にまとめた。`search.cpp`・`seed_search.cpp`・`gauge_wait.cpp`・`color_needs.cpp`・`main.cpp` の各自の実装を置き換えた。

| 部品 | 置き換えた重複 |
| --- | --- |
| `number` | 範囲つき整数の読み取り（3か所） |
| `drop_nuisance` | 位相が既知のおじゃま落下（2か所） |
| `each_remainder_drop` | 端数列の全組合せ（4か所） |
| `score_link`・`Bonuses` | リンクの得点（3か所）。ボーナス表を要求ごとに1回だけ読む |
| `advance_enemy` | 相手連鎖イベントの進行（2か所） |
| `state_key` | 探索ノードの重複排除キー（2か所）。JSON文字列の生成をやめた |

確認：再ビルドしたバイナリで、記録済み2124要求の再生が差分0。Fever系226件成功。

対象外として残したもの：`main.cpp` の `bounded_integer`（エラー文言が異なるため別関数のまま）、`seed_search.cpp` の `potential` と `color_needs.cpp` の発火口検査（高さの上限と選び方が異なり、同一ではない。SEARCH_PLANのP5で置き換える）、`search.cpp` の経路をノードごとにJSONで複製する処理（性能だけの問題で、今回は触れていない）、Pythonの `uncertainty.py`・`model.py` 側の同等処理（R3でnativeへ寄せる）。

### 7.2 列あふれ規則の統一（挙動を変える変更）

「おじゃまが13段を超えた分は消滅し、列あふれだけでは敗北としない」へ統一した。変更箇所は `gauge_wait.cpp`、`seed_search.cpp`、`uncertainty.outcomes`（Python）。`each_remainder_drop` からあふれの通知を外し、敗北は盤面の敗北判定だけで決める。

- 根拠：ツモについてのユーザー確認（14段目に置かれたぷよは消滅する）。おじゃまへの適用は解釈で、実機照合はしていない。
- 影響：記録済み2124要求のうち11件で返答が変化。配置が変わったのは2件で、いずれも「おじゃまを受けると敗北する」という判定が外れ、規定未満の発火（タネの失敗）から非消去の積みへ変わった。残り9件は生存候補の数や内部の予測だけの変化。一覧は `data/fever/baselines/2026-10-06-refactor-overflow-rule.json`。
- テスト226件は変更なしで成功。タネ計測・突入計測の値は6.5の基準と同じ。

### 7.3 その他

- `main.cpp` の `finish_probe` を `answer` から独立した関数へ分けた（挙動は同じ。再生で確認）。
- `test/fever_fixtures.py` を新設し、テスト間で共有する盤面・席・要求の生成を `test_fever_mode.py` から移した。7ファイルがテストモジュールではなくこのモジュールを読む。`test_fever_deadlines.py` は `ModeTests` の補助メソッドを使うため従来のまま。
- `tools/fever_check.py` の `test`・`record` が `--native`／`--solo` で指定したバイナリを対象にする。
- 既定の `bin/fever_battle/fever_battle.exe` を新しいバイナリ（SHA256 `dc99d5e7…48999`）へ置き換えた。置き換え前は `bin/fever_battle/fever_battle.pre-refactor-r2-20261006.exe` に退避。基準 `data/fever/golden/` は新しいバイナリで取り直した（2091要求すべて安定、エンジン34中33が安定、再生は差分0）。

### 7.4 R1で実施しなかったこと

- テストファイルのモジュール単位への並べ直し：226件の移動は挙動に関係しない一方で差分が大きい。フィクスチャの分離にとどめた。R3でPython側の構成が変わるので、そのときに合わせて行う。
- 既存の検証スクリプト9本の統合：過去の記録の再現手順として作業記録が参照している。回帰の確認は `fever_check.py replay` が担うので、スクリプトは残した。削除・統合するかはユーザーの判断による。

## 8. R4とR3の実施結果（2026-10-07）

### 8.1 R4：構築と戦術を1つのバイナリから呼ぶ（挙動は同じ、コミット `c74d6a3`）

- 単独エンジンの要求処理を `fever/main.cpp` から `fever/engine.cpp`（`fever::answer`・`fever::load_weights`）へ移した。`fever/main.cpp` は入出力だけを持つ。
- 対戦用バイナリが `fever/` の探索・発火方針・要求処理をリンクし、`op: "solo"` で同じ要求に答える。重みセットは要求に含める（`{"op":"solo","weights":…,"request":…}`）。
- Python側は `fever.exe` を起動せず、`SoloBuilder` が対戦用バイナリへ問い合わせる。対戦時のnativeプロセスは1つになった。
- `bin/fever/fever.exe` とそのプロトコルは残した。`BattleEngine`・`ModeBattleEngine` の引数 `solo` と `--solo` は、ブリッジ（`ama-memory-bridge/fever_mode_bridge.py`）が渡しているため受け取るだけにしてある。ブリッジ側を直すときに引数を削除する。
- 確認：記録済みの単独要求491件が、再ビルドした `fever.exe` と対戦用バイナリの `op: "solo"` の両方で同じ返答。2124要求の再生で差分0。Fever系226件成功。突入計測は同じ値（12/12、平均8.83手、最長156ms）。Tsuの `test_engine_protocol.py` 8件成功。
- `build.ps1`：`fever_battle` が `bench_fever` と同じソース構成（共有エンジン＋`fever/` の `main.cpp` 以外）を使う。個別ファイルの手書き列挙をなくした。

### 8.2 R3：プロトコル検査の共通化（挙動は同じ）

- `BattleEngine.observed_side` に、protocol 2 と 3 が共通して要求する検査（キャラ、可視ツモと周期の一致、盤面、予告、履歴）をまとめた。
- protocol 3 の `mode_side` は、モードとゲージを偽った複製（`normal_view`）を親クラスへ渡すのをやめ、`observed_side(side, unknown_history=True, blocked_spawn=True)` を呼ぶ。
- 複数の誤りを同時に含む要求で、最初に報告される誤りの順序が変わる場合がある。テスト226件と再生は差分なし。

### 8.3 R3の残りの扱い（方針の修正）

第3節R3の「判断はnativeへ」は、**現在のPython実装をそのままC++へ写す形では行わない。** `fever_defense.py`・`uncertainty.py`・`gauge_wait.py`・`normal_colors.py`・`mode_tactics.py` と `mode_engine._normal` の梯子は、SEARCH_PLANのP3（通常・予告ありの戦術探索の統合）とP5（フィーバー中の順位の置き換え）で、1つの尺度を持つnativeの探索に置き換わる。先に写してから置き換えると同じ箇所を二度書くことになるため、nativeへの移行はP3・P5の実装として行う。

R3として今後も残る作業：`model.py`（入力検査・得点・審判の同居）の分割。P3・P5でPythonから消える部分が決まってから行う。

### 8.4 反映

既定の `bin/fever_battle/fever_battle.exe`（SHA256 `a667e86d…710f5`）と `bin/fever/fever.exe`（`42e5d5f5…95fb8`）を置き換えた。置き換え前は同じフォルダーの `*.pre-refactor-r4-20261007.exe`。フィーバー用のプロセスが動いていないことを確認してから行った。基準 `data/fever/golden/` は取り直し済み（2091要求すべて安定、再生は差分0）。

ブリッジ側は変更していない。ブリッジは従来どおり `--solo` を渡して起動でき、エンジンはそれを使わない。

## 9. R5・R6の実施結果（2026-10-07）

### 9.1 R5：共有部分を揃える

- `irregular-form` の未コミット変更を `1fd53ff` として区切ったうえで `fever` へ取り込んだ（`02bad49`）。競合は4ファイル（`ai/search/beam/eval.cpp`・`quiet.cpp`、`test/core_speed_test.cc`・`test_core_speed.py`）で、どれも同じ速度改善を両側で別々に書いたものだったため `irregular-form` 側を採った。
- 6.1で「`fever` にだけある共有ファイルの変更が21ファイル」と書いたうち、速度改善は `irregular-form` にも同じものがあり、取り込みで一致した。
- 取り込み後に残る `fever` だけの差は意図したもので、揃える対象ではない。
  - Tsuの敗北判定を `field.get_height(2) > 11` から `field.is_dead(rule::TSU)` に置き換えた行（8ファイル・計15行）と、`core/field.h`・`core/move.h` へのフィーバー用の宣言。`core/rule.h`・`core/piece*` に依存し、これらは `AGENTS.md` でフィーバー専用の新規ファイルと定めている。
  - `test/speed_bench.cc` と `build.ps1` のフィーバー用ターゲット。
- `ai/search/beam/form.h` の `std::size` への置き換え（Linuxでのビルド用）は規則に依存しないので `irregular-form` に入れた。

### 9.2 R6：共有エンジンの整理（`irregular-form` で実施し `fever` へ取り込み）

| 変更 | コミット | 内容 |
| --- | --- | --- |
| `pvp/main.cpp` の分割 | `01ddadc` | プロトコル（重みセット・盤面と席の文字列表現・要求と返答）を `pvp/protocol.h`、エンジン2種を `pvp/engine.h` へ移した。既存の `simulator.h` と同じく `namespace pvp` の中で読み込む断片。`main.cpp` は1271行から682行。コードは移動のみ |
| `ai::think` の分割 | `7f7b096` | 約870行の1関数を、防御・相手連鎖への速攻・とどめ・牽制の4関数と、それらを順に試す本体に分けた。各ブロックは一字一句そのまま移し、判断に使う値は `Situation` にまとめて同じ名前で参照する。順序と条件は変えていない |

確認（`irregular-form`）：
- 変更前後のバイナリで、固定シードの6試合（抽象審判・`--fast`）の全ログ917行が一致。
- `bench` シード1〜4が時間の列以外すべて一致（盤面を含む）。
- `test_engine_protocol`（8件）・`test_pvp_simulator`（3件）・`test_chain_quality`・`test_core_speed`・`test_form_evaluation` 成功。

確認（取り込み後の `fever`、`899b873`）：Fever系236件成功、記録済み2148要求の再生で差分0、上と同じTsu側のテストと `bench` の一致。

注意：フレーム単位の審判（既定）での対戦ログは、同じバイナリを2回走らせても一致しない（思考時間が進行に影響する）。そのため一致の確認は抽象審判で行った。抽象審判でも、同じバイナリの2回の実行で1行だけ返答の付随情報が異なった（手は同じ）。

### 9.3 実施しなかったもの

| 候補（6.2） | 理由 |
| --- | --- |
| `ai/search/dfs/` と `beam/` の評価部品の共通化 | 同一行は多いが、対象の関数を読んで差を確かめる作業が要る。Tsuの対戦判断に直結し、固定シードで確かめられる範囲（6試合）では足りない |
| `beam.cpp` と `fever/search.cpp` のビーム本体の共通化 | `irregular-form` のビームの呼び出し方を変える必要がある。P2で `fever/search.cpp` に `aim` を足したため、共通化の形を先に決め直す必要がある |
| 盤面と文字列の変換の統一（`pvp/protocol.h` と `fever/text.h`） | 行数14の向き・文字が同じかを確かめてからにする。今回 `pvp` 側を1ファイルにまとめたので、次の作業はしやすくなった |
| `ai/path.cpp`・`bench` の整理 | 調査（6.2）で利得が小さいと判断した |

### 9.4 反映

- `fever`：**既定の `fever_battle.exe`・`fever.exe` は置き換えていない。** 置き換えようとした時点でフィーバー対戦のプロセスが動いており、ファイルが使用中だった。既定は探索の再編後のビルド（SHA256 `9484ef20…68e4`）のままで、取り込み後のビルドは `bin/r6/` にある。両者は記録済み2148要求に同じ返答をする（挙動の差はない）。基準 `data/fever/golden/` は既定のビルドに対するもの。
- `irregular-form`：**実行中の `pvp.exe`（Tsuの対戦に使用中）は置き換えていない。** 新しいビルドは `C:\Users\ho_ki\git\ama\bin\r6b\pvp.exe` にあり、既定の `bin/pvp/pvp.exe` への反映はユーザーが対戦を止めたときに `build.ps1` で行う。


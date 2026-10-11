# 初回15連鎖@40手ベンチマーク

2026-10-12。F40-0のベンチ・現行器adapter・既存応答からの診断を実装し、小規模回帰を確認した。B1/B2、新探索、学習、製品統合は未実施。[研究計画](FEVER_FIRST40_RESEARCH_2026-10-12.md)、[仕様](FEVER_CHAIN15_PROTOTYPE_SPEC.md)を参照。

後続の[F40-1内部診断](FEVER_FIRST40_DIAGNOSTICS_2026-10-12.md)では、本B0をコミット状態で再現し、独立workerのobserverを実装した。本書の「内部診断未測定」はF40-0作成時の記録。B0ベンチ自体は変更せず、診断は別入口/sidecarで保存する。B1/B2は引き続き未実装。

## 対象と停止条件

研究専用入口は `tools/bench_fever_first40.py`。戦術のanswer()を通さず、現行 `_normal_options/_solo_build` の容量検査・発火選択・Python採用を含む通常構築を評価する。既存search.cpp/fire.cpp、対戦戦術、既存ベンチ、config・既定exeは今回変更していない。

- 空盤面・通常モード・周期位相0から、設置Pieceの累計を1〜40手で数える。整理消しで時計を戻さない。
- 最初の実10以上が初回本線。15以上なら成功、10〜14ならその場で失敗終了。40手目の実15を含み、41手以降やセカンドを数えない。
- 1〜9は継続し、1〜3 / 4〜6 / 7〜9を記録する。
- 死亡・配置不能・timeout・エラー・40手初回未発火を分母から除外しない。今回の明示指示に従い、実15と同じ遷移で死亡した場合も失敗（保存48試行に該当なし）。
- @30/@35は同じ40手試行から集計する。expected_chainや発火準備を成功にしない。

native queueの試作splitmix4色モデルであり、Steam実機の成功率・操作・対戦成績ではない。shape周期と色生成を区別する。全消し後もタネ配布/Fever突入を行わない。

## 共通APIと比較条件

`fever_battle/first40_benchmark.py` の `Observation` は盤面、現在＋NEXT2の3Piece、キャラ、絶対設置数、周期index、観測した消去履歴だけを持つ。環境seedと4手目以降は含まない。`Backend.choose(observation)` はx/rと実遷移予測next_field/next_chainを返す。processes()/close()で費用を測り解放する。環境は独立native workerで実queue/transitionを管理する。

現行LegacyBackendだけを提供する。将来の独立研究器もこのAPIを実装できる。`--candidate LABEL=PATH` は同じnative soloプロトコルの別バイナリを同じadapterで比較する入口。新探索の実装ではない。全candidateの遷移は参照native環境で検証し、同じseed/盤面/判定を使う。対照はCLIの最初のlegacyで、ラベルの辞書順で変えない。

基準は可視3・250×8・仮想6列/native threads・margin1、逐次実行。内部深さ・発火方針を期限向けに変えず、環境停止だけを加えたB0。**総wall予算の強制打切りは未実装。** 既存IPC各requestの10秒timeoutと、研究用250ms/手は別物。計測結果から250ms以内の返却保証を主張しない。

## 実行と再現性

出力先は毎回新しいディレクトリを使う。既存ディレクトリは拒否し、過去結果を上書きしない。

```powershell
python tools/bench_fever_first40.py build --output bin/research_first40/build
python tools/bench_fever_first40.py run --native bin/research_first40/build/fever_battle.exe --build-manifest bin/research_first40/build/build.json --seeds 31004 31010 --output bin/research_first40/smoke
python tools/bench_fever_first40.py replay --experiment data/fever/baselines/2026-10-11-chain15-research/current-mode.json --output bin/research_first40/replay
python test/test_fever_first40.py
```

runの両キャラは同じseedを使う。seed-start/countも指定可能。seed-role development/holdoutは記録であり、未使用seedであることを自動保証しない。31001〜31024は開発用。最終200以上/キャラの前に使用履歴と仕様を凍結する。

buildは既存build.ps1で専用exe/DLLを生成し、compiler版/hash、command、build log、source snapshot、HEAD/dirty statusを保存。runはソース・config・データ・exe/DLLのSHA256、ソースzip、tracked patchを保存する。指定されたbuild manifestとsource/binaryの一致も検査する。外部candidateのbuildを使う場合、そのbinary hashだけから元ソースを断定せず、別途build manifest/snapshotを添付する。

## ログと診断の限界

manifest.json、results.json、summary.json、steps.jsonlを保存する。各試行終了時にcheckpointし、全予定試行完了とsource/config/binary不変でcomplete=trueになる。中断データはcomplete=falseで残る。

JSONLにはbefore/after、実3ツモ、実配置、実links、色消去数、実transition.discarded、絶対手数/残り手数、残容量、中央2列の安全高さ、思考wall/CPU、容量理由とsafe/retaining/improving数、可視fire手数、保持/延長採用、仮想depthを記録する。input + before − popped − discarded = afterを検査する。容量74とmargin1時72は生存する静止盤面の総セル上限であり、合法手数ではない。

未提供のsearch_nodes、幾何Witness、root消失、尾の到達可能性はnull/unavailable。容量解除から構造的不可能・探索不足を因果判定しない。保存ログではdiscardedを収支から推定し、古いsolver返答値も別名で保持する。原ログは編集しない。

wallはPython容量検査・solo・保持採用・IPC込みのchoose呼出。実遷移の外側検証・初期化・解放は含めない。失敗したchooseの経過時間も集計。CPUはdriver＋backend native＋environment nativeのuser/kernel秒（初期化後〜解放前）。CPU/wallのcore相当と論理CPU数で割ったホスト換算率を区別し、ホスト全体の実CPU率とは呼ばない。native各processの生涯ピークworking setを保存し、合計同時ピークとは呼ばない。Python driverのピークメモリ・現行nativeのノード数は未測定。

率は全開始試行の分母とWilson95%。成功手数の全リスト・成功例の条件付き中央値・全試行の成功累積50%到達有無を分ける。整理消しとの関連は因果効果ではない。対応比較はseedごとのgain/loss/差を保存する。最終採否の対応bootstrap/McNemar、同wall予算のキャンセル器はF40-3/4の未実施事項。

## 検証結果

[成果物](../data/fever/baselines/2026-10-12-first40-benchmark/README.md) に保存。

| 保存24試行/キャラ | ラフィーナ | ラフィソル |
| --- | ---: | ---: |
| 初回15@30 | 1/24（4.2%） | 2/24（8.3%） |
| 初回15@35 | 6/24（25.0%） | 4/24（16.7%） |
| 初回15@40 | 6/24（25.0%） | 5/24（20.8%） |
| @40 Wilson95% | 12.0〜44.9% | 9.2〜40.5% |
| 初回13 / 14終了 | 5 / 9件 | 4 / 5件 |
| 40手初回未発火 | 2件 | 6件 |
| 成功者中央値 | 32.5手 | 32手 |

保存48試行・1635手の新集計が前報と一致。旧CPU/メモリはログに無く、遡及推定しない。

専用buildは `bin/first40-benchmark/build/fever_battle.exe`（SHA256 `7b11653608df287c6f55121f5f74c98655fd1fee88387602eb7a4121f90cd13f`）、DLL `9186363b9a3619c4f69226e158eb28c0f784cb13854849b71ebf3f855e4a609c`。HEAD `465953ed7cefdd3a4c68fbdc8319fcb9242da13c`＋開始時の未コミット状態を含む。build manifest/snapshotをライブ実験manifestに記録。

回帰seed31004/31010を両キャラで実行し、4試行120手のbefore/queue/配置/after/links/容量/方針が旧ログと一致。ラフィーナ35手15・25手10、ラフィソル28手14・32手15で終了。旧fire_moves未提供時の0と新nullは表現差として正規化した。最初の照合ではこの表現差で停止したが、配置・連鎖の不一致ではなかった。

同一nativeを別candidate名で呼ぶ1seed試験も25手一致、gain/lossとも0。これは比較入口の検査であり新器の性能ではない。各2試行の50%を未知seedの成功率推定に使わない。

小規模liveのwall（mean/P95/max）はラフィーナ104.7/160.0/176.7ms、ラフィソル94.8/155.4/159.7ms。CPU合計30.906/28.062秒、計測窓wall6.342/5.745秒、4.87/4.88 core相当。旧24試行との対応速度比較ではない。

意味的テスト13件、Tsu protocol8件成功。Tsu同seed1/2 benchの時間以外全列一致（130470点53手・132900点37手）。開始時429既存ファイルは今回の文書追記前に全て不変、既定3exe hash不変を確認。

コミット/pushは未実施。前半「まずコミット・push」と末尾「承認後」が衝突するため末尾を優先し、開始時manifest/差分/429ファイルsnapshotを `bin/first40-benchmark/preflight/` に保存した。承認後、既存変更と今回の追加を区別してコミットする。新探索の採否・切替は今回のベンチ実装に含めない。

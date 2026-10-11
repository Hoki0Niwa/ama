# 初回15連鎖@40：F40-1探索内部診断

2026-10-12。基準コミット `9c90eede0f0e05176f4dd86363cf29eb186f3f99`、診断コードの凍結コミット `0f67724`。F40-1までを実装・検証した。**ビーム内の候補多様性の縮小と幾何15候補の脱落は観測したが、多様性不足が初回15失敗の主因であるという証拠は不十分。** B1/B2・新評価・配置の切替は実装していない。

## 1. コミット状態のB0再現

9c90eedのgit archiveを固定した独立ディレクトリで、既存build.ps1・B0ベンチを再実行。幅250、深さ8、可視3、仮想6列、margin1、空盤面・周期位相0、試作splitmix4色列、両キャラ同seed31001〜31024。48試行1635手の盤面・配置・実links・方針・容量・廃棄が旧ログと一致した。

| 実発火指標・分母各24 | ラフィーナ | ラフィソル |
| --- | ---: | ---: |
| P15_first@30 | 1/24 | 2/24 |
| P15_first@35 | 6/24 | 4/24 |
| P15_first@40 | 6/24（25.0%） | 5/24（20.8%） |
| 初回13 / 14 | 5 / 9 | 4 / 5 |
| 初回未発火@40 | 2 | 6 |

意味的13件、Tsu protocol8件、Tsu seed1/2の時間以外全列一致（130470点53手・132900点37手）を確認。B0の再現実行中にTsu検査が一部重なったため、そのwallを性能比較の対照には使わない。以下の98固定局面比較は他のビルド・ベンチと並行せず、3条件の呼出順を巡回させて測定した。

## 2. 独立した研究診断

製品search/evaluation/fire/engine・共通Tsu・既存Python backend・config・battle_policy・既定exe/DLLに変更なし。`tools/build_fever_diagnostics.py` が元search.cpp/evaluation.cppの確定anchorを検査し、研究用translation unitへ読み取りobserverを挿入する。生成ソース・元ソース・compiler・command・binaryをhashで記録し、Fever研究workerにだけリンクする。元のLayer.add、TT比較、PRUNE_CHAIN、root順位、仮想色列、深さ、発火判断を維持する。

`research_diagnostics=true/false`で切替。research_placed_totalは絶対設置数で、moves_since_chainから推定しない。探索入力は実盤面・現在/NEXT2・キャラ/位相・観測履歴だけ。環境seedや4手目以降は渡さない。診断soloはseed・可視4以上・初回期限外の診断時計を拒否する。外側の保存ファイルにあるseedは観測の索引であり、探索器の入力ではない。

各仮想列・各層・各rootに以下を保存する。

- 親数、合法配置試行数、drop失敗、死亡、安全余白除外、合法子数、TTのactionによる切断、実5以上の枝刈り、幅による却下/置換、生存数。
- 幾何Witness Lg（仮の鍵で消えるリンク数）、Eg（色消去合計−4Lg）、Rg（仮消去後の色数）、Kg、Xg、鍵色、Hg（元盤面の中央2列margin余白）。Xgは発火列であり尾の位置ではない。
- rootの検索結果、展開親ノード数、配置試行数、B0評価回数、診断だけの追加potential回数、実探索深度、層のwall/thread CPU・仮想列のwall・検索全体のwall/process CPU、native RSS/生涯ピーク、診断保存領域の下界。

summaryは全rootのカウンタと各root/脱落理由の代表Witness、allは全候補の数値tupleを残す。default summaryで全候補の盤面や全Witnessを保存したとは言わない。allでも盤面は代表例だけを保存し、全候補はboard hashで識別する。元heapとの生存multiset収支を毎層照合。完全同一の盤面/root/scoreの経路は観測上等価として扱い、経路ごとの別IDは作らない。

TTは短いhashとclampしたevalを使う。診断では実盤面のWitnessを必要に応じてコピー上で再計算するが、B0のevalには戻さない。TT切断時のchild.evalは未評価の継承値であり、幅で選ばれた候補のevalと順位比較しない。追加計算をB0評価回数へ混ぜない。

生存するbeam子孫が無くなっても、rootの最終結果自体は候補ベクトルに残る。root消失数はbeam内の将来展開経路の消失であり、初手を返せなくなった件数ではない。実5以上の枝刈りも幅・TTによる脱落と分ける。

## 3. 23失敗試行の途中局面

初回13/14で終わった全23試行について、終端の10手前・5手前・1手前・終端を保存観測から再評価（92局面）。ラフィーナ31004・ラフィソル31010の成功対照を各3局面加え、計98局面。各観測で参照B0・診断OFF・診断ONの完全応答（search_ms/診断キーを除く）とPython採用後の実配置がすべて一致した。

98局面の合計は展開親674,121、配置試行9,641,976、B0評価4,363,731。幅却下5,602,670、幅置換655,868、TT切断43,831、実5以上枝刈り695,255。診断追加potential285,368回（B0評価数の約6.5%相当）。ノード・仮想列・同じ試行の複数観測を独立な性能標本として数えない。

89/98局面でrootのbeam子孫が縮小した（13終端群35/36局面、14群52/56、成功対照2/6）。この差は局面時期と容量にも依存する関連であり、失敗原因の割合ではない。

幾何Lg≥15の幅/TT脱落例があったのは5局面。summaryの代表例31件を独立した解として数えない。これら5局面を探索的にallモードで追跡し、残った候補と盤面hash・幾何signatureを比較した。追跡を追加の独立試行や採用評価にしない。

| 観測 | 本線結果 | 脱落した異なる盤面数 | 幾何盤面の時刻 | 残ったLgの最大 | 解釈 |
| --- | ---: | ---: | --- | --- | --- |
| ラフィーナ31002・38手 | 13 | 10 | 44手 | 16 | 全て期限後 |
| ラフィーナ31014・24手 | 14 | 36 | 30〜31手 | 15〜16 | 未知の仮想色を含む別構造が脱落 |
| ラフィソル31006・32手 | 14 | 8 | 38手 | 15 | 未知の仮想色を含む別構造が脱落 |
| ラフィーナ31004・30手 | 15成功 | 101 | 36〜37手 | 15〜16 | 成功試行でも脱落する |
| ラフィソル31010・27手 | 15成功 | 6 | 31〜32手 | 15 | TT例には同盤面が別rootで生存するものもある |

「異なる盤面」は同じ層で生存した盤面とhashが異なることを確認し、仮想列/層を跨ぐ重複を除いた。例：ラフィーナ31014ではroot12にEg5/Rg4/Kg3/Hg1/発火列2のLg15が脱落。ラフィソル31006ではroot5にEg9/Rg2/Kg3/Hg0/発火列2のLg15が脱落した。列番号は0始まり。

**全ての該当層にLg15以上の候補が残っていた。** また5観測とも、B0は既に仮想列上で実際のpopを伴う15を見つけていた。これは現実の初回15実発火ではない。捨てた15を残せば改善するという説明だけでは、残った15が現実のツモで完成しない問題を説明できない。

観測された期限内の失敗群の脱落は2局面で、いずれも深さ7以降。現在/NEXT2を越える仮想色と仮の単色鍵に依存する。鍵が合法Piece/操作で追加できること、残り期限内に置けること、未知色に頑健なことは証明していない。発火口や連鎖尾の同一構造を持続追跡する識別子も今回作っていない。幅による多様性縮小は確認できたが、**実現可能な初回15@40の解を捨てたという証拠は得られていない**。

## 4. 費用

98固定局面のchoose（容量・Python採用・IPC・診断JSONの出力/解析込み）。trace圧縮・分析はこのwall外。

| 条件 | 平均ms | P95ms | 最大ms | driver＋当該native CPU合計秒 |
| --- | ---: | ---: | ---: | ---: |
| 参照B0 | 60.1 | 133.3 | 159.1 | 28.922 |
| 診断OFF | 65.3 | 151.6 | 174.8 | 31.859 |
| 診断ON | 137.1 | 300.7 | 630.0 | 47.109 |

診断OFFにもobserver呼出の費用が残る。OFF平均は参照より約8.6%増、ONは約2.28倍。ONには8局面の全tuple出力を含む。診断費用を新しい探索方式の費用や改善として扱わない。250ms打切りや実対戦向け軽量化は実装しない。

nativeの生涯ピークworking setは参照9.54MB、OFF9.55MB、ON74.77MB。診断driverを別processから100ms周期で監視し、ピークworking set146.64MB・全処理CPU51.359秒を記録した。MBは10^6 bytes。生涯ピーク、観測時RSS、storage下界を区別し、processピークの和を同時ピークとは呼ばない。C++のbeam wall/CPUはJSON serializationの前、外側chooseはその費用も含む。beam展開数には容量/可視発火探索の展開数を含めない。

## 5. 再現と検証

[データとmanifest](../data/fever/baselines/2026-10-12-f40-diagnostics/README.md)。source snapshot/生成ソースhash/compiler/hash/全コマンドを保存。参照exeは `e0cc8f91d5edb7d851b9f1cd6cfce01de26f09f45178f72b491e0c0200365eda`、診断exeは `3980df0481c52dd8e3d01ef1c4a65ef66dee58dddd2202ffe23d1df02ba0543e`。生成元9c90eed＋診断コード0f67724の内容をsource hashで照合する。研究exeだけをビルドした。

```powershell
python tools/bench_fever_first40.py build --output bin/research_f40_diag/reference
python tools/bench_fever_first40.py run --native bin/research_f40_diag/reference/fever_battle.exe --build-manifest bin/research_f40_diag/reference/build.json --count 24 --output bin/research_f40_diag/b0-results
python tools/build_fever_diagnostics.py --output bin/research_f40_diag/build
$env:AMA_TEST_F40_REFERENCE = (Resolve-Path bin/research_f40_diag/reference/fever_battle.exe).Path
$env:AMA_TEST_F40_DIAGNOSTIC = (Resolve-Path bin/research_f40_diag/build/fever_battle.exe).Path
python test/test_fever_first40_diagnostics.py
python tools/diagnose_fever_first40.py --reference-native $env:AMA_TEST_F40_REFERENCE --diagnostic-native $env:AMA_TEST_F40_DIAGNOSTIC --build-manifest bin/research_f40_diag/build/build.json --baseline bin/research_f40_diag/b0-results/results.json --output bin/research_f40_diag/observations --detail-focus
```

意味的13＋研究6（native4含む）＋Tsu protocol8が成功。層ごとのheap収支、全tupleのEg=消去数−4Lg、root別幅却下/置換/生存、12Witnessの独立resolve、OFF/ON/reference応答、未来/seed/不正時計拒否を確認。既存製品ソース・設定・既定バイナリの不変を照合した。

さらにseed31004/31010を両キャラで最初から終了までOFF/ON対応実行（4対応・8試行、240配置）。全配置・実消去・容量判断・初回終了が参照B0と一致。ラフィーナ35手15/25手10、ラフィソル28手14/32手15を双方で再現した。既知の回帰例であり、各2件の成功率を未知列の性能推定に使わない。

ここでF40-1を終了する。B1/B2の実装・候補予約・期限による探索変更・Value/rollout・製品切替・独立holdoutは行わない。この診断だけからB2の効果を予測せず、次工程へ進む判断はユーザーに戻す。

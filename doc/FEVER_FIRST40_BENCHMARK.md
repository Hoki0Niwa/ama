# 初回本線の得点ベンチマーク

この研究の主指標は `Pscore_first@40`。15連鎖そのものではなく、初回本線1回の実得点で判定する。次の研究の比較基準候補はS0G。条件付きの古いP15集計とは別schemaで扱う。

## 成功・終端の契約

| キャラ | ID | 目標得点T |
| --- | --- | ---: |
| ラフィーナ | raffina | 160520 |
| ラフィソル | rafisol | 166840 |

空盤面・通常・標準周期の位相0から始め、Pieceの設置を1〜40手で数える。最初の実10連鎖以上が初回本線。1〜9の整理は継続し、手数を戻さない。

最初の本線がT以上なら成功、T未満ならその場で失敗終了。10〜14連鎖でもT以上なら成功。40手目を含み、41手以降・セカンド・累積点を数えない。同時死亡は失敗。未発火・死亡・配置不能・timeout・エラーを分母から除かない。@30/@35は同じ試行から集計する。

得点は実消去群の通常倍率で計算し、落下点・全消しの別報酬・相殺換算・Fever倍率・仮想発火を含めない。全消し後のタネ供給とFever突入はこの構築課題にはない。

## 観測・方策API

`fever_battle/first40_benchmark.py` の `Observation` は盤面、現在手＋NEXT2、キャラ、絶対設置数、周期index、観測した消去履歴を持つ。seed・4手目以降・試行IDをActorへ渡さない。

`Backend.choose(observation)` はx/rと `next_field`／`next_chain` の予測を返す。独立native環境の `placements`／`transition` で合法性・実遷移・得点・廃棄・死亡を照合し、`processes()`／`close()` で費用と子プロセスを管理する。

| 方式 | 内容 |
| --- | --- |
| B0 | 凍結した通常構築の容量検査・可視発火・Python採用を含む基準器 |
| S0 | 可視3ツモ以内でTへ届く初回発火証明Fがあれば発火し、なければ同じB0 |
| S0G | S0と同じ。盤面の色ぷよ＋期限内可視Piece個数N<40の時だけprobeを省く |

N=40はprobeする。不正・未検証形式は省略で隠さず元の検査へ委譲する。省略は `not_run_mass_impossible`、`score_probe_complete=null`、probe実時間null、追加遷移0。40個は実10以上の必要条件で、15連鎖必須条件ではない。

## 比較条件・再現

S0G比較は可視3、幅250、深さ8、仮想6列、最大6thread、margin1、総choose250ms、probe25ms／16000遷移。総時計はprobe→B0でリセットしない。失敗chooseの時間も費用へ含める。色源は試作splitmix4でSteamの成功率ではない。

```powershell
python tools/bench_fever_firstscore40_s0_mass_gate.py --help
python tools/bench_fever_firstscore40_s0_mass_gate.py preflight --output bin/research-s0g-preflight
python test/test_fever_firstscore40_s0_mass_gate.py
```

再現時の比較仕様は [実験契約](contracts/README.md)。CLIの `preflight/replay/fixed/smoke/run` を順に使う。参照nativeとplannerはそれぞれ `--native`／`--build-manifest`、`--planner`／`--planner-build` で指定し、source/binary/hashが一致するmanifestを用意する。既定のローカル成果物がないcheckoutでは先に復元・照合する。新しい出力先を使い、過去結果を上書きしない。

得点審判は `tools/bench_fever_firstscore40.py`、S0の独立確認は `confirm_fever_firstscore40_s0.py`、P15の再現入口は `bench_fever_first40.py`。P15は最初の実10以上を境界に15未満を失敗とする別契約で、得点率へ合算しない。

## 記録と評価

manifestにsource/config/native/plannerのhash・snapshot・ビルド条件・seed役割を保存する。各手の公開before/queue/配置/after/links/score/discarded、残手数、容量、採用F、wall/CPUを記録する。資源収支 `input + before − popped − discarded = after` を照合する。

全開始試行を分母に率・Wilson区間を出す。方式間のgain/loss、同seedの両キャラをクラスタにした区間、成功者限定中央値と全試行累積率を分ける。source/settingsを測定中に調整しない。既知群・開発群・新しい確認群は別表にする。

生データ・manifest・凍結仕様はGit除外の `data/fever/baselines/` またはローカルバックアップにある。結果と証拠ディレクトリは [RESEARCH_RESULTS.md](RESEARCH_RESULTS.md)、次の実装は [SELFPLAY_RL_PLAN.md](SELFPLAY_RL_PLAN.md)。

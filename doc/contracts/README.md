# 実験の再現契約

ベンチマークが `experiment-spec.md` として保存する仕様。作業計画や変更履歴ではなく、再現時の方式・終端・比較条件を定義する。数値設定・判定の正本は各ツールと `data/fever/research/` の設定。

| 契約 | 入口 | 位置付け |
| --- | --- | --- |
| [期限付き構築B1](FIRST40_DEADLINE.md) | `bench_fever_first40_deadline.py` | P15の開発比較 |
| [根の候補評価R1](FIRST40_ROOT_EVALUATION.md) | `evaluate_fever_first40_roots.py` | 保存局面からの条件付き比較 |
| [S0独立確認](FIRSTSCORE40_S0_CONFIRMATION.md) | `confirm_fever_firstscore40_s0.py` | 得点契約、loss0条件の確認 |
| [S0G資源検査](FIRSTSCORE40_S0_MASS_GATE.md) | `bench_fever_firstscore40_s0_mass_gate.py` | 次の研究基準候補の対応比較 |

新しい実行ではこの仕様のhashを記録する。保存済み実験の正確な仕様は、各ローカル成果物の `experiment-spec.md` とmanifestを使用する。編集後の本書を保存済み試行の凍結仕様と同一視しない。原データ・過去の採否条件は書き換えない。

共通の得点契約は [ベンチマーク](../FEVER_FIRST40_BENCHMARK.md)、測定の結論は [研究結果](../RESEARCH_RESULTS.md)、次の工程は [学習計画](../SELFPLAY_RL_PLAN.md)。

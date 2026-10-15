# S0C：得点発火S0の独立確認契約

入口は `tools/confirm_fever_firstscore40_s0.py`。設定は `data/fever/research/firstscore40_s0_confirm_v1.json`。凍結したB0/S0だけを比較し、H1や構築評価の変更を混ぜない。

## 条件

成功・終端は [得点契約](../FEVER_FIRST40_BENCHMARK.md)。ラフィーナ160520点、ラフィソル166840点。最初の実10以上が40手以内にTへ届けば成功。同時死亡優先、1〜9は継続。累積・セカンド・仮想点を数えない。

61001〜61064、各キャラ64、2方式の256試行。可視3、幅250・深さ8・仮想6、総choose250ms、probe25ms。probeとB0は同じ総期限を使う。既知smokeや再生は主率へ加算しない。

`preflight`、公開要求再生、意味的回帰、smokeを通してから主比較へ進む。全開始試行と失敗費用を含め、同seedの両キャラをクラスタとして差を評価する。F採用後の期限内発火・予測遷移の一致を監査する。

## 判定と記録

この確認契約はloss0・timeout0を要求する。改善幅・統計・早期達成・F監査・P95/CPU条件と合わせ、ツールの `gate()` と設定JSONで判定する。後続S0Gの緩和された条件をこの試行へ遡及適用しない。

raw、全steps、設定、native/planner、凍結source/specification、全gain/loss、失敗ログとhashを新規出力先へ保存する。旧試行の救済再実行や結果の上書きはしない。保存済み仕様は成果物のコピーを使う。[結果](../RESEARCH_RESULTS.md)。

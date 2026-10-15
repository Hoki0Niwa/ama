# 独立Feverシミュレーターとの接続

オフラインの完全対戦・学習環境は `C:/Users/ho_ki/git/fever-simulator` が所有する。AmaはAI・探索・評価・エンジンAPI、ブリッジは観測・入力・ランチャーを担当する。

## 用途と実行

C++20のイベント駆動審判で、通常→突入→タネ交換→復帰→勝敗を進める。全26キャラ、52タネ、倍率、相殺、2系統予告、時計、マージン、並列試行、記録・再生、学習用batch APIを扱う。

```powershell
python C:/Users/ho_ki/git/fever-simulator/tools/ama_selfplay.py --ama-root C:/Users/ho_ki/git/ama-fever --seed 0 --matches 4 --workers 2 --output bin/simulator-check --audit
```

Amaの `ModeBattleEngine`／nativeを2席へ接続し、現在手＋NEXT2と同時刻の公開観測を渡す。席別設定は `--seat-config`・`--seat-width`・`--decision-budget-ms` を使い、正確な引数形式は同ツールの `--help` を参照する。再生はシミュレーターの `fever_simulator.exe --replay`。Ama側 `fever_battle.replay` は別の明示イベント形式用。

## 色源と時間

`steam_seed32` は元処理の21000手、タネ抽選・強制色補正455例との照合を記録している。`training_chacha12` は長い学習列用で、独立実装147456色と照合。両色源を同一の評価分布としない。

simulation_revision 4では、元処理の生成・飛散・列抽選・地形運動を照合し、保存Steam148区間の連鎖時間で誤差0F。学習384試合16061遷移とAma12決着／12再生の896教師遷移を検査している。これは学習済みモデルや実機勝率の完成を意味しない。

仕様・校正の正本は同リポジトリの `docs/SPECIFICATION.md`、`TIMING.md`、`VALIDATION.md`、Ama接続は `AMA_INTEGRATION.md`、学習は `TRAINING.md`。

## 確認範囲と制約

制御末尾、入力、共有乱数、配送・到着順などには推定や未照合が残る。環境の連鎖時間一致をAmaの時間予測・入力一致へ自動的に読み替えない。

実機と同じ席設定の5seed比較では、全5リプレイが再生一致し、同条件の再走も同一。実機の勝者とは3/5一致で、手数・最大連鎖・Fever突入は相違した。prefetch・実入力遅延・壁時計探索を完全再現しておらず、5標本の勝敗一致を精度として使わない。

出現列が塞がった局面で、接続が現在Pieceの実姿勢を渡せず停止する制約がある。未完走を敗北や成功へ置き換えず、比較の全試行へ含めて報告する。

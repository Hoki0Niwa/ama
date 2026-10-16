# 独立Feverシミュレーターとの接続

オフラインの完全対戦・学習環境は `C:/Users/ho_ki/git/fever-simulator` が所有する。AmaはAI・探索・評価・エンジンAPI、ブリッジは観測・入力・ランチャーを担当する。

## 用途と実行

C++20のイベント駆動審判で、通常→突入→タネ交換→復帰→勝敗を進める。全26キャラ、52タネ、倍率、相殺、2系統予告、時計、マージン、並列試行、記録・再生、学習用batch APIを扱う。

```powershell
python C:/Users/ho_ki/git/fever-simulator/tools/ama_selfplay.py --ama-root C:/Users/ho_ki/git/ama-fever --seed 0 --matches 4 --workers 2 --output bin/simulator-check --audit
```

Amaの `ModeBattleEngine`／nativeを2席へ接続し、現在手＋NEXT2と同時刻の公開観測を渡す。席別設定は `--seat-config`・`--seat-width`・`--decision-budget-ms` を使い、正確な引数形式は同ツールの `--help` を参照する。再生はシミュレーターの `fever_simulator.exe --replay`。Ama側 `fever_battle.replay` は別の明示イベント形式用。

## 色源と時間

`steam_seed32` は元処理の21000手、タネ抽選・強制色補正455例との照合を記録している。タネ抽選の乱数は色表の生成（1,587回）後のゲーム管理乱数から始まり、飛散（1個5回）とも共有する（revision 7）。`training_chacha12` は長い学習列用で、独立実装147456色と照合。両色源を同一の評価分布としない。

simulation_revision 11（2026-10-16時点）。元処理の生成・飛散・列抽選・地形運動を照合し、保存Steam148区間の連鎖時間で誤差0F。元コードから移植したもの：

- 得点式・倍率表・マージン（revision 6）
- 攻撃の発射と到着・同一フレームの処理順（revision 7）
- 組ぷよの操作処理（`src/control.*`）。審判では任意の `control_model=source_control`（revision 8）。既定は従来の到達判定と代表値14F。
- パッドの席の出現待ちの入力バッファ（revision 9）
- でかぷよの色変更回転（revision 11）。A で次の色（赤→緑→青→黄）、B で前の色。位置と向きは変わらない。
- 攻撃オブジェクトの開始処理とおじゃまトレーの3段階（revision 10、既定 `delivery_model=source_tray`）。攻撃は発射時に受け手の予告へ飛行中として入り、保留に数える。相殺は作成時と到着時の2回。

revision 9 では、実機ログ（`docs/CAPTURE_FORMAT.md`）の入力をそのまま再生する行動と、比較ツール `tools/compare_capture.py` も加えた。実機ログはまだ取っておらず、比較はシミュレーター自身が作った合成記録でしか検査していない。これらは学習済みモデルや実機勝率の完成を意味しない。

Amaの仕様のうち、倍率表・タネ基準の更新・マージン曲線・おじゃま列順・突入／交換／復帰の区間の記述は、2026-10-16に同リポジトリの抽出値・解析へ合わせた。対応と残る相違は [検証](VALIDATION.md)。

仕様・校正の正本は同リポジトリの `docs/SPECIFICATION.md`、`TIMING.md`、`VALIDATION.md`、Ama接続は `AMA_INTEGRATION.md`、学習は `TRAINING.md`。

## 確認範囲と制約

入力時間（代表値14F）、攻撃の到着フレーム、通常全消し交換・落下なし復帰の実機捕捉などは未照合。共有乱数・同一フレーム順・マージンはコードで確定したが実機捕捉では未照合。環境の連鎖時間一致をAmaの時間予測・入力一致へ自動的に読み替えない。

実機と同じ席設定の5seed比較では、全5リプレイが再生一致し、同条件の再走も同一。実機の勝者とは3/5一致で、手数・最大連鎖・Fever突入は相違した。prefetch・実入力遅延・壁時計探索を完全再現しておらず、5標本の勝敗一致を精度として使わない。

出現列が塞がった局面で、接続が現在Pieceの実姿勢を渡せず停止する制約がある。未完走を敗北や成功へ置き換えず、比較の全試行へ含めて報告する。

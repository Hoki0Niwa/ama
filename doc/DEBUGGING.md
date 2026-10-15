# 症状の調査と局所再現

長時間の対戦を繰り返す前に、失敗局面の候補・経路・要求を固定する。候補検査、判断の冷間再投入、同seedの実走はそれぞれ確認できる内容が異なる。

## ログに残すもの

ブリッジのセッションログはUTF-16 JSONL。`duel ready` のengine hash、席別設定、`match seed`、`seed config`、`planning`、`locked`、`fire`、`seed decision`、`surprise landing` を使う。

失敗／発火／タネ判断のイベントには全 `request` を記録する。`arrival.split_rows`・`split_extra`・`model_lock_in`・`model_check_in` でちぎりと予測確認時刻を区別する。`on_target: false` や断念だけで実着地の不一致としない。次の盤面と予測を比較する。

## 到達不能局面だけを検査

```powershell
python tools/check_logged_unreachable.py extract LOG --output data/fever/baselines/unreachable-new.json
python tools/check_logged_unreachable.py check data/fever/baselines/unreachable-new.json
```

ログで失敗した盤面・Piece・配置を固定し、現在の提示手とDLL経路を検査する。既定は3個組、失敗手が残れば終了コード1。全要求のない旧ログでも使えるが、AIがその手を選ぶかは再現しない。測定済みの許可付き要求は [3個組操作仕様](DISABLED_TRIPLE_OPERATIONS.md) と合わせて読む。

## 判断要求を再投入

```powershell
python tools/replay_logged_decisions.py LOG --kind failed --round 3 --limit 10
```

保存した全要求を新しいエンジンへ渡し、`same/changed` を記録する。生きたセッションのキャッシュ・履歴を引き継がない冷間の比較なので、差が全て修正効果とは限らない。旧ログに要求がなければ未観測値を補って再現しない。

## 症状seedだけ実走

```powershell
python tools/symptom_seeds.py LOG SEEDS.txt --symptom triple_loop
```

modのseed記録とラウンドを対応させ、`seed_list` と `seed_list_end = loop` で症状局だけを回す。記録のmatch番号とセッションの開始位置を確認し、単にラウンド−1をseedと決めない。seedは色列を固定するが、相手の手と実時間は固定しないため同じ症状の再発保証ではない。

## 判断・勝敗の集計

`tools/analyze_fever_matches.py` の `--help` を参照し、`--losses` とJSON出力で敗者側の症状を調べる。キャラ・幅・先読み・バイナリ・mod周期が異なる集団は分ける。席の勝率をキャラ・方策の優劣へ直結させない。

241局の参照ログ（`input-session-20261015-081828.log`、SHA256先頭 `06afd1acf6c2`、1Pラフィソル幅200・先読みあり／2Pアリィ幅100・先読みなし）は28215設置中目標外8、操作断念2。先攻不利、相手が同等の返しを保持する所への発火、特殊組ぷよでのタネ失敗、満杯自滅が残る調査対象。この観測だけで発火時機の因果効果や修正後の勝率を断定しない。

同ログの予告未確定での降下60回では、モデルを照合できた50回中34回が予測どおり、16回が予測確認時刻の2〜9F後だった。ちぎりの延びはモデルとほぼ一致し、相手終了予測と確認時刻の誤差は未分離。既定余裕10Fの効果は [時間モデル](FEVER_TIMING.md) の範囲で評価する。

## 通常確認余裕の比較

```powershell
python tools/ab_nuisance_margin.py --sim-root C:/Users/ho_ki/git/fever-simulator --matches 100 --seed 0 --margins 10 0 --output bin/nuisance-margin-new.json
```

各seedを席入替で比較し、全予定局・未完走・降下・死亡・費用を記録する。実機とシミュレーターの降下時刻は同一と確認されていない。実機効果は同じ定義の `surprise landing` と予測時刻で別に確認する。

# 3個組の操作制限と測定済み許可

`fever/operation_suspensions.h` が停止条件の正本。候補生成と操作DLLで同じ入力辺を止める。L/Jは同じ幾何形状なので両方へ適用する。

## 停止する操作

| 条件 | フラグ | 現行の扱い |
| --- | --- | --- |
| 12段の列へ引っ掛けて軸を13段へ上げる | `triple_hooks_enabled` | false |
| 出現高さ以上で12段以上の列に当たり横へ押し戻す | `triple_high_lateral_kicks_enabled` | false |
| スポーン行からの汎用持ち上げ | `triple_spawn_row_lifts_enabled` | false。下記の測定済み条件だけ許可 |

左右反転も停止する。普通の回転、盤面端だけの押し戻し、低い床蹴り、2個組は別。停止辺を使わず到達する配置は残す。生成側だけで届くとした `measured_triple` の拡張で迂回させない。

## 停止しているモデルの例

![引っ掛けの予測と実測](images/disabled-triple-20261014/method-hook.png)

引っ掛けの旧モデルは軸を同じ列に保って上げるが、観測例は右へ移動する。分岐が一致していない。右側の同型の停止は保守的な適用で、左右双方の実測済みを意味しない。

![高段横押し戻しの予測と実測](images/disabled-triple-20261014/method-lateral.png)

高段横押し戻しは予測と同方向へ動いた例もあり、補間途中で照合が断念している。操作の断念を実着地の失敗と同一視しない。`locked` のx/rは指定値なので、次の盤面で実着地を照合する。

固定5例の全盤面・ツモ・予測・観測はローカル `data/fever/baselines/2026-10-14-disabled-triple-operations.json`。修復時は単体回転、到達、経路、入力プログラム、実着地を同じ例で照合する。

## 測定済みの持ち上げ許可（allow-list）

ブリッジの `measured_fever_inputs.lift_allowances()` が測定済み3個組プログラム28件の条件を作り、要求の `lift_allow` で渡す。条件はゴール軸・回転・一致列高さ・高さ上限・満杯ゴール許可。未指定・空配列ではスポーン行持ち上げを全て抑止する。

`core/operation.*` の `MeasuredLift` と `set_measured_lifts` が一時許可を管理し、`piece_move.cpp` は条件一致の候補だけ追加する。`normal_space.h` のキャッシュ鍵へ許可表の世代を含め、`fever_battle/main.cpp` の `lift_allowances` と `mode_engine.apply_lift_allow` で接続する。

許可判定はブリッジの `select` と同じ条件で検証する。一致列が変わった盤面に別プログラムを流用せず、2個組や停止中の引っ掛け・高段横蹴りを解放しない。

## 確認方法と限界

```powershell
python test/test_fever_operations.py
python tools/check_logged_unreachable.py check data/fever/baselines/2026-10-15-unreachable-placements.json
```

固定したログの3個組100局面で失敗手を提示しないことを検査する。これはゲームで失敗した配置を基準とする候補検査で、ライブラリ間の一致だけを実機成功としない。

症状seed2/8/16と成功seed5/7/15/23の7局・130設置では3個組の目標外・到達不能再試行・断念0。許可がある時だけ現れる持ち上げ4盤面は、測定済みプログラムで4/4設置一致した。全局面の保証ではなく、旧失敗の完全な再現でもない。2個組の壁寄り失敗は別に残る。

停止辺を再有効化する際は、正しい終点・手順を実測し、停止のテストを実測の回帰へ置き換える。高さの許容だけを緩めて成功扱いにしない。

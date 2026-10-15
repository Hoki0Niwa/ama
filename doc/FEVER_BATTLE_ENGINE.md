# 通常対戦API（protocol 2）

`python -m fever_battle.engine` は通常モード・ゲージ加算0の検証用入口。実機のFever対戦は [protocol 3](FEVER_MODE_ENGINE.md) を使う。盤面ワーカーと構築探索は `bin/fever_battle/fever_battle.exe`、観測照合は `observation.py`、明示イベント審判は `model.py` が担当する。

```powershell
./build.ps1 -Target fever_battle
python test/test_fever_battle.py
python -m fever_battle.engine
```

## 対戦要求

例は全て架空の観測。ゲージ設定の実機確認には使えない。

```json
{
  "protocol_version": 2,
  "rule": "fever_normal_battle",
  "match_id": "match-001",
  "frame": 120,
  "observation": {"frame_before": 120, "frame_after": 120, "match_status": "running"},
  "gauge_gain_on_offset": 0,
  "target_point": 120,
  "self": {
    "observed_frame": 120, "phase": "controllable",
    "moves_since_chain": 0,
    "character": "raffina", "mode": "normal", "gauge": 0,
    "dropset_index": 0, "piece_id": 0,
    "field": ["......", "......", "......", "......", "......", "......", "......",
              "......", "......", "......", "......", "......", "......", "......"],
    "queue": ["2:RG", "2:BY", "L:RRG"],
    "confirmed": 0, "unconfirmed": 0, "remainder": 0
  },
  "enemy": {
    "observed_frame": 120, "phase": "controllable",
    "moves_since_chain": 0,
    "character": "arle", "mode": "normal", "gauge": 0,
    "dropset_index": 0, "piece_id": 0,
    "field": ["......", "......", "......", "......", "......", "......", "......",
              "......", "......", "......", "......", "......", "......", "......"],
    "queue": ["2:RG", "2:BY", "2:RG"],
    "confirmed": 0, "unconfirmed": 0, "remainder": 0
  },
  "solo_options": {"beam_width": 250, "beam_depth": 16, "margin": 1}
}
```

`phase` は `controllable`／`placing`／`chain`／`waiting_seed`。自分は操作可能なときだけ判断する。相手が連鎖中等なら現在手で即発火できるとは報告しない。`field` は上から14段、最上段は空、浮いたセルは拒否。`queue` は現在手＋NEXT2まで。色はR/Y/G/B、おじゃまは#。キャラIDは周期から一意に推定せず、明示する。

観測不能なゲージ、予告、端数等を0で埋めない。現段階では必要な観測が不足する要求は拒否する。観測の責務はブリッジ側にある。`moves_since_chain` は4連鎖以上の直後に0へ戻す建築手数で、ブリッジ側の観測履歴から管理する。

返答は `x`（0始まり）、`r`（U/R/D/L）、リンクごとの `link_points`、`next_field`、判断理由、決定を識別する試合・フレーム・ツモ・周期IDを含む。でかぷよの `r` は色添字で、`color` を併記する。ゲーム内の回転ボタン回数とは別で、実際の入力経路はブリッジが作る。

入力前に `authorize_reply(要求, 返答, 最新の観測)` を使う。時刻が進んでも両者の判断対象の状態が変わっていなければ使える。ツモ・盤面・予告・モード・試合等が変わった返答は捨てて再計画する。ポーズ・終了中の要求や混在フレームは拒否する。通常のみの検証APIであり、実機のFever対戦はprotocol 3を使う。


## 再生と自己対戦

`python -m fever_battle.replay LOG.json` は `state` と `events` を持つログを検証する。各配置・得点・相殺・終状態の再生であり、勝率の実測ではない。

完全なFever自己対戦は別リポジトリ `C:/Users/ho_ki/git/fever-simulator` で行う。対戦のログ形式と再生バイナリは同リポジトリの仕様に従う。通常のみのAPI・審判を完全対戦環境と扱わない。

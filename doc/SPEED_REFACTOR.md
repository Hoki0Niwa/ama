# 共通Ama基盤の速度改善（2026-10-04）

`fever` ブランチの既存worktreeへ、通版で実装・検証した共通演算の高速化を移植した。移植前の基準は `f223c60`。このブランチはFever固有機能の設計段階であり、今回のビルド・測定対象は既存の共通Ama基盤と2個組の探索である。段階A〜Eの達成状況は変わらない。

## 変更

- `core/field.*` / `core/fieldbit.*`：小さなSIMD演算と初期化をinline化し、共通の消去処理を使う連鎖数のみの経路 `pop_count()` を追加。
- `ai/search/beam/quiet.*` / `eval.cpp`：評価で参照しない得点・消去マスクの保存を省略し、既に集計した列の高さを候補生成へ渡す。得点を使う探索は従来の経路を維持する。
- `ai/search/beam/table.*`：置換表を探索終了時に解放し、所有権のコピーを禁止、moveを追加。
- `build.ps1` / `test/core_speed_test.cc` / `test/test_core_speed.py`：このブランチの既存ターゲットのWindowsビルドと、共通処理の回帰検証。
- `test/speed_bench.cc`：旧新比較用の内部ベンチマーク。ブリッジ用のエンジンプロトコルではない。

探索幅・深さ、仮想ツモ列、候補順、重み、得点計算のルールは変更していない。このブランチの `config.json`（`build.form=50`）と既存のPEXT切替を使う。通用ブリッジの接続先は変えていない。

## 測定

記録された24局面を固定し、各3回、新旧の呼出し順を反転しながら計測した。両版を同じGCC 15.1.0、`-std=c++20 -O2 -msse4.1 -DNDEBUG -static -s` で構築。既存クライアントに合わせて現在・NEXTの2組を渡した。下表は各局面の3回の中央値をグループ内で平均した値で、実ゲームの入力・演出時間は含まない。

| 探索 | 局面数 | 旧版 | 新版 | 短縮 |
| --- | ---: | ---: | ---: | ---: |
| 50×8 | 12 | 61.80 ms | 42.00 ms | 32.0% |
| 250×16 | 12 | 496.93 ms | 335.31 ms | 32.5% |

候補ごとの期待得点・静的評価・選んだ配置と配置後の盤面は**72/72回一致**した。

12×3の探索を61回実行し、1回目から61回目までのPrivate Bytesを比較した。旧版は192,184,320バイト（183.28 MiB）増加し、新版は659,456バイト減少した。旧版の約3 MiB/探索の増加が解消した。短期のメモリ値にはアロケーター・スレッドによる変動も含まれる。

## 検証と再現

- `puyop`、`test`、`tuner`、`speed-bench` のビルド成功。
- core回帰2件成功。CPU機能を確認し、ソフトウェアPEXTとBMI2の両方で実行。各版2000盤面のスカラー参照モデル比較、500盤面・575候補の静止探索比較、置換表の所有権移動を確認。
- 実ゲームへの入力、Feverの特殊ツモ・ゲージ・種・時間・対戦機能は今回の検証対象に含まれない。

Fever worktreeで実行する：

```powershell
.\build.ps1
.\build.ps1 -Target test
.\build.ps1 -Target tuner
.\build.ps1 -Target speed-bench
python test/test_core_speed.py
# 明示的にBMI2を使うビルドは -Pext（BMI2対応CPU用）
```

旧ソース・入力・全測定は `C:\Users\ho_ki\git\ama-memory-bridge\observations\fever-speed-20261004` に保存した。旧版はその `before/` 内の共通ソースから同じビルドスクリプトで作成している。

```powershell
# ブリッジのルートで旧版をビルドし、比較
& observations/fever-speed-20261004/before/build.ps1 -Target speed-bench
python observations/fever-speed-20261004/benchmark.py
```

旧新の識別情報と設定ハッシュ、要求・応答・全試行は同ディレクトリの `comparison.json`。今回のベンチマーク実行ファイルのSHA-256は次のとおり：

- 旧版：`82eae4f98fc52388ac23a9c899d8f7c7d97aa6a09ef158f65bb57a78ce197a24`
- 新版：`b51c688e54da2b9dd73ec62707159388cb65c343fd214249ea291a8aedd391a3`

Fever用の対戦エンジンやラフィーナの大連鎖能力が完成したという意味ではない。次の開発は既存の計画どおりP0の仕様確定から進める。

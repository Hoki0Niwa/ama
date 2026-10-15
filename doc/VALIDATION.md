# 検証方法と確認範囲

## 実行する確認

```powershell
python tools/fever_check.py test
python tools/fever_check.py replay
python test/test_engine_protocol.py
```

`test` はFeverの自動検証、`replay` は `data/fever/golden/` の記録済み要求との一致を調べる。Tsuに触れる共有変更では、このリポジトリの `build.ps1` でビルドし、同一seedの `bench` で時間以外の列を比較する。

テスト成功、ビルド成功、再生一致、実機入力、対戦の強さは別の確認。文書だけの変更で過去のテスト件数を今回の実行結果として転載しない。時間制限のある対戦ログは同じバイナリでも変わり得るため、固定seedのログ一致だけを互換性の根拠にしない。

## 証拠の所在

- `data/fever/golden/`：Git管理の要求と期待返答。
- `data/fever/seeds/`：公開参照タネ。4系統50盤面、未収録パターンあり。
- `data/fever/baselines/`：Git除外の測定JSON・生ログ・ソース／バイナリsnapshot・hash。新cloneには含まれない。
- `C:/Users/ho_ki/git/ama-baselines-backup/`：ローカル証拠のバックアップ。該当ファイルの有無とhashを確認して使う。

仕様を読むだけで測定済みとせず、条件・出所・残る制約を添える。古いcommit hashは履歴整理で変わることがあるため、証拠はsource/binary/configのhashとmanifestで照合する。

## 確認できていることと限界

| 対象 | 確認範囲 | 残る制約 |
| --- | --- | --- |
| 全26キャラ周期 | Steamの16手。24キャラは選択図、隠し2キャラは実プレイ | 全キャラを16手ずつ置いた確認ではない。modは別周期 |
| 配置・連鎖 | 全形状・上端・Tsu互換の参照モデル検証。Steam非消去76配置一致 | 上端消滅順・天井・全経路の実機保証なし |
| 時間 | 通常1202リンク、Fever49リンクの部分校正 | 未観測盤面・入力・配送・交換の普遍的上限なし |
| 公開タネ | 50盤面×5形状の条件付き検証で遷移再生一致 | 有利な現在色を選んだ幾何検証。ランダムツモ成功率ではない |
| 対戦戦術 | 固定局面・API・記録要求の自動検証 | 全26キャラの総合受入れ、実着弾と勝率の校正は未完了 |

次の作業は [実装計画](IMPLEMENTATION_PLAN.md)。個々の変更履歴はGit/GitHubで確認する。

## 研究の評価

契約は [FEVER_FIRST40_BENCHMARK.md](FEVER_FIRST40_BENCHMARK.md)、条件・全失敗・統計と費用は [RESEARCH_RESULTS.md](RESEARCH_RESULTS.md)。S0Gの比較実行時には新18＋既存59の77 Python検査、5411公開観測の再生とF213件の保持を確認した。今回や将来のcheckoutでそのまま成功すると推定しない。

研究の総250ms、probe25ms、splitmix4、標準周期と、現在の実機AIを分ける。学習とSteamの改善は未検証。研究source/config/native/rawを変えずに文書を保守する。

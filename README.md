# Ama Fever

ぷよぷよeスポーツ（Steam版）のフィーバールールで戦うAI。作業ブランチは `codex/fever-first40-benchmark`。

初回本線の目標得点@40手を改善する研究。S0Gを比較基準とし、次の候補は通常構築の教師初期化と小規模PPO。製品への統合と学習は未実施。

## 開発の入口

- [文書一覧と現在の対象](doc/README.md)
- [実装計画・未完了事項](doc/IMPLEMENTATION_PLAN.md)
- [検証方法と確認範囲](doc/VALIDATION.md)
- [作業ルールとリポジトリの責務](AGENTS.md)
- [TsuエンジンのビルドとAPI](ENGINE.md)

```powershell
./build.ps1 -Target fever_battle
python tools/fever_check.py test
```

実機の観測・入力・ランチャーは別リポジトリ `ama-memory-bridge`、自己対戦環境は `fever-simulator` が担当する。起動・接続は [実機接続](doc/FEVER_MODE_LIVE.md) を参照。

Tsu用の `bin/pvp/pvp.exe`、単独構築用の `bin/fever/fever.exe`、対戦用の `bin/fever_battle/fever_battle.exe` は別の入口。Feverの対戦仕様は [protocol 3](doc/FEVER_MODE_ENGINE.md) にまとめる。

## 謝辞・ライセンス

Amaの探索は K. Ikeda、D. Tomizawa、S. Viennot、Y. Tanaka による Playing PuyoPuyo: Two search algorithms for constructing chain and tactical heuristics、[puyoai](https://github.com/puyoai/puyoai)、[takaptのビーム探索](https://www.slideshare.net/slideshow/ai-52214222/52214222) を参考にしている。[nlohmann/json](https://github.com/nlohmann/json) と [rapidhash](https://github.com/Nicoshev/rapidhash) を使用する。

[MIT License](LICENSE)。元プロジェクトは [citrus610/ama](https://github.com/citrus610/ama)。

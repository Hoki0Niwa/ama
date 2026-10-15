# 実機の起動・先読み・入力

AIはAma、メモリ読取・仮想パッド・入力実行・先読みのスケジュールは `C:/Users/ho_ki/git/ama-memory-bridge` が担当する。

## 起動

Ama側で対戦バイナリと操作DLLをビルドする。

```powershell
./build.ps1 -Target fever_battle
```

ブリッジのランチャーで **AI同士の対戦（フィーバー）** を選び、2席のパッド割当・ゲーム側ゲージ設定・フォーカスを確認する。CLIはブリッジ側で実行する。

```powershell
python control.py session --mode fever-battle --backend hidmaestro --execute
```

`--execute` 省略は入力なし。F6は両AIのオン／オフ、F9は停止、Ctrl+F9は終了。`fever-duel` は単独構築AIを測る別モード。バイナリ・Python・設定の変更を稼働セッションへ反映するには再起動する。

## 判断と先読み

- protocol 3のPython入口とnative workerを使う。対戦構築はworker内の `op=solo`。ツモは現在手＋NEXT2まで。
- 配置判断後に次の既知状態を別プロセスで準備する。構築部分の再利用と、戦術を含む完成判断の再利用を区別する。
- 相手連鎖・レート変化中の準備は `speculative` な向け先。出現時に最新戦術を再判断し、同じ配置ならキーを引き継ぐ。
- 未確定予告の量だけで操作を取り消さない。実盤面・ツモ・世代・操作状態・確定落下・Fever時計・攻撃期限は検査する。
- 消去や確定落下で次盤面が未知なら実観測を待つ。開始前の準備に使うのは観測した空盤面と可視ツモで、開始前の入力は行わない。

## 操作の実行

操作DLLの現在位置からの経路を使い、入力の各結果を観測する。先行入力は許可された純粋な横移動を基本とし、高段回転はDOWNを離して行う。限定された2個組壁越え終端の同時入力は [操作API](../docs/OPERATIONS.md) に従う。

経路開始前に盤面・可視ツモ・世代を照合し、経路中は自分の設置番号・モード・処理段階・期限を確認する。同じ組ぷよを操作する間は相手の表示変化だけで経路を止めない。設置・連鎖・落下・タネ交換・終了で入力を離す。経路不一致では実姿勢と到達先を確認し、観測の高さを緩めて成功扱いしない。

特殊形状の切替直後は、新しいPieceと前の固定位置の座標が一時的に混在し得る。操作可能な現在Pieceの観測を待つ。`wait`・演出・結果画面では入力しない。終了時は入力を離してworkerと子プロセスを閉じる。

## 状態と診断

`garbage_phase` や途中接続で不足した履歴を推定しない。不明端数列はエンジンで評価し、実落下後に再観測する。相手の連鎖中は最後の直接観測固定盤面へ元フレームと状態を添え、今発火できる盤面と誤認しない。

ログは `planning`、`locked`、`fire`、`seed decision`、`surprise landing`、承認拒否理由を照合する。`search_reused` と `normal_build_search_reused` は意味が異なる。観測の制約は [FEVER_MODE_OBSERVATION.md](FEVER_MODE_OBSERVATION.md)、確認範囲は [VALIDATION.md](VALIDATION.md)。

症状の局所再現は [DEBUGGING.md](DEBUGGING.md)。判断要求・`match seed`・`seed config`・`arrival` の時刻診断を保存し、再走は症状シードへ限定できる。3個組は [測定済み許可](DISABLED_TRIPLE_OPERATIONS.md) の対象だけを持ち上げる。

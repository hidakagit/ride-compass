---
description: ユーザーが手動で進めるタスクの前提の一覧と、それぞれが済んだかを出す（残り0なら開始してよい）
argument-hint: <Txxx>（手動で進めるタスク）
---

# 手動タスクの前提

前提の一覧は仕掛中のダッシュボードで持つ（1件の形は`docs/conventions/asking-user.md`「仕掛中のダッシュボード」節、
前提に入れる基準は`docs/conventions/orchestration.md`「ユーザーが手動で進めているタスク」節）。

1. `ArtifactData`の`list`（url `https://claude.ai/artifact/E8G458My7xPA8RpbkU3RWF`・collection `pending`・
   `query.limit` 1000）に`out_dir`を付け、このセッションのscratchpadの下の新しいディレクトリへ書き出す。
2. `python scripts/orchestrate.py prereqs $ARGUMENTS --pending <1.のディレクトリ>`を実行し、出力を要約する。
   - 先頭に「前提N件・残りM件」を置き、残りの前提を状態（稼働中なら担当・判断待ち・振り出し待ち・
     停止中・未着手）と一緒に並べる。
   - 残り0なら「開始してよい」とはっきり書く。
   - 前提を足す・外すのはダッシュボードの件で行う（kind `前提`の件を`set`・`delete`）。記録を書き換えるコミットにも
     状態の表にもしない。前提を先に進めるなら`/orchestrate:priority --prereqs-of <Txxx> 高`。

このコマンドはリポジトリも状態の表も書き換えない。

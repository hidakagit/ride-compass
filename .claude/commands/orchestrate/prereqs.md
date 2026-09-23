---
description: ユーザーが手動で進めるタスクの前提の一覧と、それぞれが済んだかを出す（残り0なら開始してよい）
argument-hint: <Txxx>（手動で進めるタスク）
---

# 手動タスクの前提

`python scripts/orchestrate.py prereqs $ARGUMENTS`を実行し、出力を要約する。

- 先頭に「前提N件・残りM件」を置き、残りの前提を状態（稼働中なら担当・判断待ち・振り出し待ち・
  停止中・未着手）と一緒に並べる。判断待ちで前提に入れていないものは別に示す。
- 残り0なら「開始してよい」とはっきり書く。
- 前提の一覧に足す・外すは`--add`・`--remove`（前提に入れる基準は
  `docs/conventions/orchestration.md`「ユーザーが手動で進めているタスク」節）。前提を先に進めるなら
  `/orchestrate:priority --prereqs-of <Txxx> 高`。
- このコマンドはリポジトリを書き換えない（`--add`・`--remove`のときだけ状態の表を書き換える）。

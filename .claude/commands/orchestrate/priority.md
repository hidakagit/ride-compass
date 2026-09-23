---
description: 振り出し待ちのタスクの優先度を設定する（--prereqs-of で手動タスクの前提をまとめて）
argument-hint: <Txxx>... <高|中|低>  または  --prereqs-of <Txxx> <高|中|低>
---

# 振り出し待ちの優先度

`python scripts/orchestrate.py priority $ARGUMENTS`を実行し、結果を1〜2行で返す。`--prereqs-of <Txxx>`のときは、
手動タスクの前提がダッシュボードにあるので、先に`/orchestrate:prereqs`の1.と同じく書き出し、`--pending <そのディレクトリ>`を
足して実行する。

- 振り出し待ちは優先度の小さい順（高→中→低）に、前提が済んだものから取り出される
  （`board dispatch pop`）。優先度を上げても、前提が済むまでは振り出されず、回の母集団の外のタスクは
  取り出されない（規約「回の始まりと終わり」）。
- 「振り出し待ちに無い」と出たタスクは、稼働中・完了・未登録のどれか。未登録なら
  `board dispatch push`で積んでから設定し直す。
- 変更のあと`python scripts/orchestrate.py board dispatch list`の並びを添える。

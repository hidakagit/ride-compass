---
description: 振り出し待ちのタスクの優先度を設定する（高・中・低）
argument-hint: <Txxx>... <高|中|低>
---

# 振り出し待ちの優先度

`python scripts/orchestrate.py priority $ARGUMENTS`を実行し、結果を1〜2行で返す。

- 振り出し待ちは優先度の順（高→中→低）に、前提が済んだものから取り出される
  （`board dispatch pop`）。優先度を上げても、前提が済むまでは振り出されず、回の母集団の外のタスクは
  取り出されない（規約「回の始まりと終わり」）。
- 手動タスクの前提を先に進めるなら、`python scripts/orchestrate.py check`（または`status`）が出す前提の番号を並べて
  `高`にする。
- 「振り出し待ちに無い」と出たタスクは、稼働中・完了・未登録のどれか。未登録なら
  `board dispatch push`で積んでから設定し直す。
- 変更のあと`python scripts/orchestrate.py board dispatch list`の並びを添える。

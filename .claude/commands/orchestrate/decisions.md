---
description: ユーザーの判断待ち（状態の表の未回答と、タスク記録の保留）をまとめて選択式の質問で出す
argument-hint: [Txxx（省略時は全件）]
---

# 判断待ちをまとめて出す

確認依頼の形式は`docs/conventions/asking-user.md`が正本。先に全文読む。

1. `python scripts/orchestrate.py decision list`を実行する。状態の表の未回答（`D-xxx`）と、
   台帳の未完了タスクの記録にある保留（「ユーザー決定」と書かれていないもの）が出る。
   `$ARGUMENTS`があれば、その番号の分だけに絞って扱う。
2. 記録の保留は、そのままでは問いにならない。1件ずつ記録を読み、asking-user.mdの形（何の画面・
   機能か／いまどうなっているか／なぜ決めるか／各選択肢で利用者に何が起きるか。推奨を先頭に）へ
   整えて`decision add`で状態の表へ積む。**「記録の保留が判断に足る形で書かれていない」印の
   付いたもの**は、記録から背景・選択肢を補えなければ問いにせず、担当（いなければ司令塔の
   キュー）へ「保留の書き直し」として回す。
3. 画面の見た目・情報量に関わる問いには、変更前と変更後の実画面かモックを添える。
4. `python scripts/orchestrate.py decision list --json`の形を土台に、選択式の質問
   （`AskUserQuestion`）で4問ずつ出す（各2〜4択、推奨を先頭に「（推奨）」）。
5. 回答を`python scripts/orchestrate.py decision answer <D-xxx> <選択肢>`で状態の表へ記録する。
   記録由来の保留なら、その`Txxx.md`の保留へ「ユーザー決定（日付）」を書く作業を担当の
   エージェントへ返すか、`python scripts/orchestrate.py board todo push "<Txxx>へ<D-xxx>の決定を反映" --priority 5`
   で司令塔のキューへ積む。

このコマンド自身はリポジトリを書き換えない（書き換えるのは状態の表だけ）。記録への反映は
担当エージェントの仕事である。

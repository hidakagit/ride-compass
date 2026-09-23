---
description: 仕掛中のタスクのうち、決めてほしい問いだけを選択式で聞き、答えを仕掛中のダッシュボードへ書く
argument-hint: [Txxx...（省略時は全件）]
---

# 決めてほしい問いを聞く

問いの形の正本は`docs/conventions/asking-user.md`（全文）、置き場は同じ文書の「仕掛中のダッシュボード」節。先に読む。

**出すのは問いだけ**——ダッシュボードのkind `保留`で答えの無いもの。実行してほしい操作・
改善案・起票案・前提は出さない（それはダッシュボードのページ）。

1. **集める**: `ArtifactData`の`list`（url `https://claude.ai/artifact/E8G458My7xPA8RpbkU3RWF`・collection `pending`・
   `query.limit` 1000）。kind `保留`で`answer`が空のもの（引数があれば`task`で絞る）。
2. **問いに整える**: 1件ずつ本文を読み、asking-user.mdの形（何の画面・機能か／いまどうなっているか／なぜ決めるか／
   各選択肢で利用者に何が起きるか。推奨を先頭に）へ整える。背景・選択肢を補えなければ問いにせず、担当（いなければ
   司令塔のキュー）へ「保留の書き直し」として回す。画面の見た目・情報量に関わる問いには、変更前と変更後の実画面か
   モックを添える。
3. **聞く**: 選択式の質問（`AskUserQuestion`）で4問ずつ（各2〜4択、推奨を先頭に「（推奨）」）。
4. **書く**: 答えはダッシュボードのその件の`answer`へ、答えの文に日付を添えて書く（`ArtifactData`の`update`、読んだ
   `version`を`if_version`に付ける）。記録へ移すのは、そのタスクのコミット（担当へ`SendMessage`で返すか、
   `python scripts/orchestrate.py board todo push "<Txxx>へ問いと答えを書く: <答え>" --priority 5`）。閉じたタスクの
   答えは`asking-user.md`「閉じたタスクに残った問いに答えが出たら」のとおり。

このコマンド自身はリポジトリを書き換えない（ダッシュボードの`answer`だけを書く）。

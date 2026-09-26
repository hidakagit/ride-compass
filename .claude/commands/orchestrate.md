---
description: 司令塔として、改善計画のタスクを複数エージェントへ振り分けて並行で進める
argument-hint: [--concurrent N（同時に動かす上限。既定3）] [対象（省略時は台帳の未完了のうち着手可能なもの）] [手動で進めている番号]
---

# 並行実行（司令塔）

`docs/conventions/orchestration.md`を全文読み、その規約に従って司令塔を務める。手順・判断基準・
エージェントへ渡す共通ルール・改善の回し方の正本はすべてその文書にあり、ここには書かない
（このファイルは呼び出し口であって、写しを持つと古くなる）。

引数:

- `--concurrent N`: 同時に動かす本数の上限（既定3）。`python scripts/orchestrate.py board run limits.concurrent=N`
  で状態の表へ書く。
- 手動で進めている番号があれば、規約の「ユーザーが手動で進めているタスク」節に従って、
  影響のあるタスクを候補から外してから振り分ける。

機械で回す手続き（詳細は規約の該当節）:

- 起動したら`python scripts/orchestrate.py board claim`を1回実行する（このセッションを司令塔として
  記録し、道具を使うたびの定期確認がこのセッションで走るようにする）。直後のフックが「記録した」と
  知らせなければ登録されていない（「記録されていない」と出たら、単独のコマンドで実行し直す）。
- **振り出す前に毎回`python scripts/orchestrate.py gate`。NGなら振り出さない**（理由を返す）。
- 定期確認は`python scripts/orchestrate.py check`（フックが確認間隔ごとに自動で走らせる）。
- 状態の表は手で書かず`python scripts/orchestrate.py board ...`で更新する。
- 監査は`python scripts/orchestrate.py audit <名前> <sha>`を先に回し、未判定の項目を自分で見る。

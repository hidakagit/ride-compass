# 作る・確かめる

作る担当・確かめる担当・開発機の対話のセッションが、PR を作って master へ入れるまでの手順。流れの決まりは [flow.md](flow.md)。
コードのリポジトリ（hidakagit/ride-compass）へは hidakagit の名義で打ち、置き場へは `GH_TOKEN=$FLOW_BOT_TOKEN` を付ける。

## 作る

1. **ブランチ**: `git fetch origin`。`orch/tasks-<番号>` が GitHub にあれば `git checkout -B orch/tasks-<番号> origin/orch/tasks-<番号>` のあと
   `git merge origin/master`、無ければ `git checkout -B orch/tasks-<番号> origin/master`。`wip/tasks-<番号>-*` の枝があれば、要るものを取り込んで枝を消す。
2. **依存**: `git diff --name-only origin/master -- backend/requirements*.txt frontend/package-lock.json` に出たものだけ入れ直す
   （backend は `python -m pip install -q -r backend/requirements-batch.txt -r backend/requirements-dev.txt`、frontend は
   `npm ci --prefix frontend` と `npx --prefix frontend playwright install chromium`）。
3. **読む・決める**: issue の本文とコメントを読む
   （`GH_TOKEN=$FLOW_BOT_TOKEN gh issue view <番号> -R ridecompass/ride-compass-tasks --json title,body,comments --jq '.title, .body, (.comments[] | "--- \(.author.login) \(.createdAt)", .body)'`）。
   - 答えの無い判断が残っていれば、作らずに問う（[flow.md](flow.md)「問い」）。
   - 直す場所で開いた issue を探し、前提を張る（[flow.md](flow.md)「段階と前提」）。開いた前提があれば、張って終える。
   - 1つの PR に収まらなければ、段階に分けて終える。
   - 開発機が要るものに当たったら、[flow.md](flow.md)「開発機が要る」のとおり返す。
   - マージのあとの残りで戻ったタスクは、残りを済ませて閉じる（`gh issue close <番号> -R ridecompass/ride-compass-tasks --reason completed`）。
     残りが時間を待つものだけなら、`field.js <番号> 着手可能日 <YYYY-MM-DD>` を入れて終え、その日に済ませたら欄を消す。
     確かめの行だけなら、本番に出てから問う。確かめの問いに未着手の答えが返ったら、確かめが済んだとしてチェックを付けて閉じる。
   - コードを変えないタスク（調査・計測）は、結果を本文に書いて確かめてほしいと問う。
4. **コミット**: `tasks#<番号>:` の件名でコミットし、`git push origin orch/tasks-<番号>`。強制 push はできないので、直しは足すコミットにする。
   手元で回す検査は [testing-operations.md](testing-operations.md)「手元の検査の回し方」が決める。
5. **PR**: `gh pr create --base master --head orch/tasks-<番号>`。題名と本文は [flow.md](flow.md)「コミット」の書式で書く
   （squash でそのまま master のコミットになる）。本文の検証に、`python backend/scripts/lost_constraints.py origin/master HEAD` が出した
   「消えた」制約の1件ずつの処置を書く。公開のリポジトリなので、本番の宛先は値でなく [tech-stack.md](../architecture/tech-stack.md)「本番の宛先」の名で書く。
   開いた PR が残っていれば、新しく出さずに push する。本文の書き換えは `gh issue edit <PR の番号> -R hidakagit/ride-compass --body-file <ファイル>`。
   - **画面の変更**: 修正の前後を「画面を撮る」のとおり撮り、`node tools/flow-gate/bin/attach.js <PR の番号> '<画像>#<見出し>' ...` で PR に貼る（画像はコミットしない）。
     貼れずに止まったら、出た文言を報告に書いて進める。画面に出ない変更は、確かめたコマンドと値を検証に書く。
   - **CI を待つ**: `gh run list -R hidakagit/ride-compass --commit "$(git rev-parse HEAD)" --event pull_request --json databaseId` で実行を引き、
     出た id ごとに `gh run watch <id> --compact -i 30 -R hidakagit/ride-compass --exit-status` で終わるまで前に出したまま待つ（Bash の `timeout` は 600000）。
     0件で `gh pr view <番号> -R hidakagit/ride-compass --json mergeable` が `CONFLICTING` なら、master を取り込んで push する。
     終わったら `gh pr checks <番号> -R hidakagit/ride-compass --required` で必須のチェックが全部 `pass` かを見る。
   - **落ちたら**: `git merge origin/master` で取り込み、直して 4 から。取り消し（`cancelled`）で終わって直すものが無ければ、`gh run rerun <id> --failed -R hidakagit/ride-compass` で流し直す。
6. **報告**: issue の本文（経緯・満たした完了の条件のチェック）を直し、PR へのリンクをコメントに書く。ゲートが検証中へ動かす。

## 確かめる

作った者とは別の者が、自分で見て確かめる。先に見るのは、完了の条件と、利用者に見える結果（画面・API の応答・テストが見る振る舞い）。

1. **見る**: `git fetch origin` と `git checkout -B orch/tasks-<番号> origin/orch/tasks-<番号>`（依存は「作る」の2）。
   PR（`gh pr view <番号> -R hidakagit/ride-compass --json title,body,comments,reviews`）・差分・issue の完了の条件を読み、
   「作る」の5と同じく CI を待って必須のチェックを見る。`lost_constraints.py` も自分で回す。
   画面の変更は、作る担当と同じ脚本で変更後を撮り、作る担当が貼った変更前と比べる（貼られた画像は、PR のコメントの
   `https://github.com/user-attachments/assets/…` をトークンを付けない `curl -sSL -o <ファイル> <URL>` で取って Read で見る）。
   流れの道具（`tools/flow-gate/bin/`）の変更は、`dispatch.js --dry-run`・`after.js --dry-run` で本物の状態に流して見る。
2. **書く**: 満たしていてもいなくても、issue に「確かめた結果」を書く。完了の条件の1件ごとに、何をどう見て何が出たかを書く。
3. **足す**:
   - ユーザーが見るべき変更（利用者に見える振る舞い・設計が変わる）なら、完了の条件に `- [ ] ユーザーが確かめる: …` を足す。マージは待たない。
   - 作る担当の着手より後に issue へ届いた依頼と、PR の範囲で master に残る小さな漏れは、完了の条件にチェックの無い行として足す（閉じる理由にしない）。
   - 残りが開発機で確かめる行だけになるなら、マージの前にラベル「開発機が要る」を付ける。
4. **閉じる**: 満たしていなければ、足りないことを書いて `gh pr close <番号> -R hidakagit/ride-compass --comment <理由>`。`gh pr view --json state` で `CLOSED` を確かめる。
5. **マージ**: 満たしていれば、確かめた完了の条件に issue の本文でチェックを付け（`gh issue edit <番号> -R ridecompass/ride-compass-tasks --body-file <ファイル>`）、
   `gh pr merge <番号> -R hidakagit/ride-compass --squash` で入れ、`gh pr view --json state` で `MERGED` を確かめる。
   残りがユーザーの確かめの行だけなら、本番に出てから同じ回で問う。
6. **競合**: master と競合したら「競合を解く」のとおり取り込む。どの塊も解けたら push し、CI を待ってからマージする。解けない塊があれば `git merge --abort` して、重なった所を書いて閉じる。

## 競合を解く

`git -c merge.conflictStyle=diff3 merge origin/master` で取り込み、塊ごとに合流点（`|||||||` の下）を両側がどう変えたかで決める。

- 片側だけが変えた: 変えた側を採る。
- 両側が別の行を変えた・足した: 両側の行を書き換えずに並べて残す。
- 両側が同じ行を変えた: 解かない（作る担当が取り込んで作り直す）。

印を編集で消して `git add <ファイル>` と `git commit --no-edit`。`git checkout --ours`・`--theirs` は使わない。

## PR のあと

ゲートが PR の出来事で動かす: 開いた → 検証中、マージせずに閉じた → 未着手、マージした → 残りが無ければ完了・あれば未着手。
PR が `CLOSED`・`MERGED` なのにステータスが動いていなければ、Claude が同じ行き先へ動かす（`move.js`・`gh issue close`）。
master へは必須のチェック（ルールセット）が通った PR だけが入り、本番へは master の CI が通った版だけが出る。

## 本番に出たか

frontend に届く変更は `/api/version`、backend に届く変更は `/health` の `commit` を読み、`git merge-base --is-ancestor <マージのコミット> <本番の commit>`
が 0 なら出ている。出ていなければ、master の CI の最新の実行（`gh run list -R hidakagit/ride-compass --workflow ci.yml --branch master --limit 1 --json databaseId,headSha`）を
待って見直す。それでも出なければ、着手可能日を翌日にして終える。問いには、ユーザーが見る版（画面右上のメニューの「バージョン表示」の版、
backend なら `started_at`）を書く。

## 分布の前後

値の偏りは PR では測らず、本番の派生を作り直すたびの記録で確かめる（[deployment-sync.md](deployment-sync.md)「派生データの作り直し」）。

## 画面を撮る

`node frontend/scripts/capture.mjs --script <脚本>` で撮る（口と使い方はスクリプトの先頭、例は `frontend/capture/examples/`）。

- 前は本番（`--app production`）、後は作業ツリーの版を本番の backend へ向けて（`--api <本番の backend>`）、同じ脚本で撮る。
- backend の応答も変わるなら、DB を読まない経路は `--backend <パスの頭>` で作業ツリーの backend に返させ、DB を読む経路は脚本の `patch` で応答を差し替える。
- 本番で開けない画面（管理画面等）は、e2e のモックの応答で、前は `--app origin/master`、後は作業ツリーの版で撮る。管理画面は脚本の口 `openAdmin` で開く。
- 撮る画面に関わる frontend の変更が、本番の版と作業ブランチの合流点（`git merge-base HEAD origin/master`）の間にあれば、前は `--app <合流点> --api <本番の backend>` で撮る。
- 脚本を作業ツリーの外に置いたら、脚本の全文と打った引数を `<details>` で畳んで PR のコメントに貼る。

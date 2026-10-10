---
name: task-work
description: "タスクを作る担当・確かめる担当として進める手順（作業ブランチ・依存・issue を読む・コミット・下書きの Pull Request・画面の撮影・確かめ・差し戻し・マージ・競合・範囲の外の気づき・終え方）。タスクに着手するとき・Pull Request を出すとき・確かめてマージするときに使う。"
---

作る担当・確かめる担当は、担当のワークフローが取り出した作業ツリーの中だけで作業し、ステータスは書かない（ゲートが事実から決める。
`docs/conventions/flow.md`「ステータスと割り当て」）。どの終わり方でも、push と issue への報告をして終える。

- **終え方**: 最後の発言は、その回の要約にする（後始末が終わりのコメントへ写す）。終わり方（PR を出した・問うた・段階に分けた・
  マージした・下書きへ戻した等）と、作ったもの・書いたもの（Pull Request・コミット・問い・issue）を番号かコミットの ID で名指す。
  手順の中で当たった流れの摩擦は .claude/skills/file-issue/SKILL.md「流れの摩擦を記録する」のとおり書く。
- **範囲の外の気づき**（今のタスクの外の製品の誤りや残骸）: 今の差分で直せるものは直す。ほかは1件ずつ、直す場所が同じ開いた issue へ
  コメントで寄せるか（探し方は .claude/skills/file-issue/SKILL.md「前後関係と組」）、無ければ起票するか、直さない理由を書き、どれをしたかを報告に書く。

**作る担当**
1. `git fetch origin`。作業ブランチ `orch/tasks-<番号>` が GitHub にあれば `git checkout -B orch/tasks-<番号> origin/orch/tasks-<番号>` のあと
   `git merge origin/master`（競合したら「競合を解く」）。無ければ `git checkout -B orch/tasks-<番号> origin/master`。前の担当の残り
   （`wip/tasks-<番号>-*` の枝）があれば要るものを取り込み、枝を消す。
2. 依存とテスト用の DB は担当のワークフローが master の版で入れてある。`git diff --name-only origin/master -- backend/requirements*.txt frontend/package-lock.json`
   で違いが出たら、backend は `python -m pip install -q -r backend/requirements-batch.txt -r backend/requirements-dev.txt`、frontend は
   `npm ci --prefix frontend` と `npx --prefix frontend playwright install chromium` で入れ直す。
3. issue の本文とコメントを読む（`GH_TOKEN=$FLOW_BOT_TOKEN gh issue view <番号> -R ridecompass/ride-compass-tasks --json title,body,comments --jq '.title, .body, (.comments[] | "--- \(.author.login) \(.createdAt)", .body)'`。
   `--comments` は本文を出さない）。下書きへ戻されたタスクなら、Pull Request のコメントも読む。CLAUDE.md と規約のとおりに作る。
   - 作る前に、答えの無い判断（方針・目的の読み・見た目の案・本番への書き込み）が残っていれば、問いに要る分だけ調べて、作らずに問う
     （.claude/skills/ask/SKILL.md「問い」）。issue の本文が「この issue で決める」としているものも、ここに当たる。
   - 自分の直す場所で開いた issue を探し、前後関係と組を張る（.claude/skills/file-issue/SKILL.md「前後関係と組」）。
   - 開発機にしか無いもので確かめる完了の条件は、同じことをテスト DB・CI で確かめる形へ書き換え、経緯に理由を書く。確かめる範囲が
     狭まるなら書き換えず、`docs/conventions/flow.md`「担当」の「開発機でしかできない作業」のとおり返す。
   - 1つの Pull Request に収まらないと分かったら、.claude/skills/file-issue/SKILL.md「段階に分ける」のとおり分けて終える。
   - マージのあとの残りは、済ませて完了の条件にチェックを付ける。時間を待つものだけが残るなら、欄「着手可能日時」に済ませられる
     日本時間を入れ（.claude/skills/file-issue/SKILL.md「ラベルと種類と欄」）、何をその日に済ませるかをコメントに書いて終える。その日に
     振り出されたら、済ませて欄を消す。確かめの行だけが残るなら何もしない（ゲートが本番に出てから確かめを問う）。
   - 段階に分けた親が振り出されたら、段階で確かめていない親の完了の条件を確かめる。
   - コードを変えないタスク（調査・計測）は、結果を本文に書いて自分の分の条件にチェックを付け、結果を見てほしいなら
     `- [ ] ユーザーが確かめる: …` の行を足す。
   - 残りが無くなれば `GH_TOKEN=$FLOW_BOT_TOKEN gh issue close <番号> -R ridecompass/ride-compass-tasks --reason completed` で閉じる。
4. `tasks#<番号>:` の件名でコミットし、`git push origin orch/tasks-<番号>` を、ほかのコマンドとつながずに1つで打つ（拒否の一覧の
   `Bash(git push *master*)` はつないだ全文に当たる）。手元で回す検査と整形は .claude/skills/run-checks/SKILL.md「手元の検査の回し方」だけが決め、
   全体は CI に任せる。作業ブランチの強制 push は断られるので、直しは足すコミットにする。
5. マージの前に済ませる本番への書き込みが要るなら、出さずに `docs/conventions/flow.md`「担当」の「自動で進めないもの」のとおり返す。
   **下書きの** Pull Request を出す（`gh pr create --draft --base master --head orch/tasks-<番号> --title <題名> --body-file <本文>`。gh の既定の
   名義のまま）。前の Pull Request が開いていれば、新しく出さずに push する。**CI は待たずに手放す**（ゲートが CI待ちにし、通れば
   レビュー可能にして確かめる担当へ渡し、落ちたか変異テストに新しい生き残りが出たら作る担当へ戻す）。戻ってきたら、落ちた検査
   （`gh pr checks <番号> -R ridecompass/ride-compass`）か変異テストの注記（Mutation PR の実行の ANNOTATIONS）を読んで直す。
   直し方は .claude/rules/testing.md「テストが落ちたときの直し方」。生き残りは、利用者や運用に見える振る舞いが変わるものだけテストを足し、
   ほかは本文の検証に1件1行で理由を書く。
   - **本文**: 題名と本文はそのまま master のコミットになる（`docs/conventions/flow.md`「コミット」）。`.github/pull_request_template.md` を
     作業ツリーの外へ写して `<…>` を埋め、`node scripts/pr-body.js <本文>` で形を照らしてから渡す。直すときは
     `gh issue edit <番号> -R ridecompass/ride-compass --body-file <本文>`。本番の宛先の値は書かず、tech-stack.md「本番の宛先」の名で書く。
   - **画面に届く変更**: 変えたコードを使う・見せる画面と状態を漏らさず、前後を `node frontend/scripts/capture.mjs --script <脚本>` で撮り
     （口と使い方はスクリプトの先頭、例は `frontend/capture/examples/`）、Pull Request のコメントに1枚ずつ貼る
     （`gh pr comment <番号> -R ridecompass/ride-compass --body <見出し> --attach '<画像>#<見出し>'`。見出しに画面・幅を書き、画像はコミットしない）。
     前は本番（`--app production`）、後は作業ツリーの版を本番の backend へ向けて（`--api <本番の backend>`）同じ脚本で撮る。DB を読まない
     backend の経路が変わるなら `--backend <パスの頭>`、DB を読む経路は脚本の `patch` で応答を差し替える。本番で開けない画面は e2e の
     モックで、前は `--app origin/master` で撮る。本番の版と合流点の間で撮る画面の frontend が変わっていたら、前は `--app <合流点>` で撮る。
     脚本の全文と打った引数は、撮ったあとのコメントに `<details>` で畳んで貼る。画面に出ない変更は、確かめ方と根拠を検証に書く。
6. issue の本文（経緯・完了の条件のチェック。マージのあとでないとできない条件だけを残す）を直し、Pull Request へのリンクを報告する。

**確かめる担当**（CI が通った検証待ちのタスク。作った担当とは別）
1. 作業ブランチを取り（作る担当の1・2）、Pull Request（`gh pr view <番号> -R ridecompass/ride-compass --json title,body,comments,reviews`）・差分・
   issue の完了の条件・変更が届く範囲を、作る担当の報告を写さずに自分で見る。完了の条件と、利用者に見える結果（画面・API の応答・
   テストが見る振る舞い）を先に見る。画面は作る担当と同じ道具・脚本で後を撮り、前は貼られた画像（コメントの添付の URL を
   `curl -sSL -o <作業ツリーの外> <URL>` で取って Read で見る）と比べる。`lost_constraints.py` も回し、「消えた」制約に本文の処置が無ければ満たしていない。
   ゲート（`tools/flow-gate/`）の変更は、事実を `tools/flow-gate/src/decide.js: decide` へ渡して出る値で見る（本物の GitHub へは書かない）。
2. 結果を、満たしていてもいなくても issue にコメントで書く（見出し「確かめた結果」。条件ごとに、何をどう見て何が出たか）。
3. 利用者から見える振る舞い・モジュールの設計が変わるなら、完了の条件に `- [ ] ユーザーが確かめる: …` を足して理由を書く（マージは待たない）。
   issue の答えがマージの前のユーザーの確認を求めていて答えがまだなら、マージせずに問う。作る担当の着手より後に届いた依頼
   （コメント）と、範囲の中で master に残る直し漏れは、完了の条件にチェックの無い行として足す（戻す理由にしない。マージのあとの残りになる）。
   開発機にしか無いもので確かめる行だけが残るなら、マージの前に対話作業の段階を起こして前提に張る。
4. 満たしていなければ、足りないことを Pull Request のコメントに書き、下書きへ戻す（`gh pr ready <番号> -R ridecompass/ride-compass --undo`。
   `gh pr view --json isDraft` が `true` になるまで打ち直す）。ゲートが作る担当へ戻す。
5. 満たしていれば、確かめた条件に issue の本文でチェックを付ける（確かめの行・マージのあとの条件・3 で足した行は付けない）。完了の条件に
   本番での前後の比べがあり、今の本番の前の値が issue に無ければ、本番を読むだけの口（`backend/scripts/prod_route_check.py` と同じ口）で
   取って書いてからマージする。読むだけの口で取れないなら、4 のとおり戻し、前の値を取る対話作業の段階を起こして前提に張る。
   `gh pr merge <番号> -R ridecompass/ride-compass --squash` でマージし、`MERGED` になるまで打ち直す。
6. master と競合してマージできなければ、`git -c merge.conflictStyle=diff3 merge origin/master` で取り込み、塊ごとに、合流点の行を片側だけが
   変えていれば変えた側を採り、両側が別の行を変えただけなら両方をそのまま残す。合流点の同じ行を両側が変えた塊が1つでもあれば
   `git merge --abort` で戻し、重なった所を書いて 4 のとおり戻す。解けたら push して終える（ゲートが CI を待ってまた渡す）。

**競合を解く**: `<<<<<<<`・`|||||||`・`=======`・`>>>>>>>` の印と残さない行を編集で消し、`git add <ファイル>` と `git commit --no-edit`。`--ours`・`--theirs` は使わない。

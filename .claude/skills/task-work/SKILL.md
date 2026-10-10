---
name: task-work
description: "タスクを作る担当・確かめる担当として進める手順（作業ブランチ・依存・issue を読む・コミット・下書きの Pull Request・画面の撮影・確かめ・差し戻し・マージ・競合・範囲の外の気づき・終え方）。タスクに着手するとき・Pull Request を出すとき・確かめてマージするときに使う。"
---

**作る担当**・**確かめる担当**のどちらも、作業は担当のワークフローが取り出した作業ツリーの中だけで行う。どの終わり方でも
（下書きの PR を出した・問うた・段階に分けた・完成で閉じた・確かめてマージした／下書きに戻した・対話作業の段階を起こした）、手順の中で当たった流れの摩擦を
.claude/skills/file-issue/SKILL.md「流れの摩擦を記録する」のとおり終え方の要約に書き、範囲の外の気づきに行き先か直さない理由を付け（下の「範囲の外の気づき」）、push と issue への
報告をして終える（手放す）。ステータスは書かない（手放したことを受けたゲートが、事実から決める。`docs/conventions/flow.md`「ステータスと割り当て」）。
次の担当を起こすのは振り出しなので、担当は触れない。

**範囲の外の気づき**: 作業の中で見つけた、今のタスクの範囲の外の製品（コード・文書・テスト）の誤りや残骸は、報告に書くだけで
終えない（流れの摩擦は上のとおり記録するだけ）。
1件ずつ、次のどれかをしてから終える。今の差分で直せるものは直す（.claude/skills/file-issue/SKILL.md「起票する」）。
1. 寄せる: 直す場所が同じ開いた issue（探し方は.claude/skills/file-issue/SKILL.md「前後関係と組」の「探す」）があれば、そこへコメントで書く（.claude/skills/file-issue/SKILL.md「起票する」の「重ねない」）。
2. 起こす: 無ければ、.claude/skills/file-issue/SKILL.md「起票する」の「書き方」のとおり起票する（種類は気づきの性質で選ぶ）。
3. 直さない理由を書く: 寄せも起こしもしないなら、その理由（答えを変えない・テストの冒頭の「ここで見ないもの」に書いた等）を書く。

どれをしたか（寄せた先・起こした issue の番号・理由）は、気づきと並べて報告（作る担当の6・確かめる担当の2）に書く。

**作る担当・確かめる担当の終え方**: 手番を終える最後の発言は、その回にやったことの要約にする（後始末が終わりのコメントへ写す。
`docs/conventions/flow.md`「担当」の「担当のワークフローの1回」の4）。終わり方（PR を出した・問うた等）と、やったこと・作ったもの・書いたもの（Pull Request・コミット・
問い・起票やコメントを足した issue）を番号かコミットの ID で名指し、読み手がそれを開いて確かめられるように書く。詳しい中身は
Pull Request・問い・issue に書き、最後の発言へ写さない。

**作る担当**
1. `git fetch origin`。作業ブランチ `orch/tasks-<番号>` が GitHub にあれば（CI が落ちた・下書きへ戻された・答えをもらって
   戻ったタスク）、`git checkout -B orch/tasks-<番号> origin/orch/tasks-<番号>` のあと
   `git merge origin/master` で今の master を取り込む（競合したら「競合を解く」のとおりに直して続け、直せなければ
   issue にコメントで書いて終える）。無ければ `git checkout -B orch/tasks-<番号> origin/master`。前の担当の残り
   （`wip/tasks-<番号>-*` の枝。担当のワークフローの後始末の4）があれば読んで要るものを取り込み、取り込んだら枝を消す
   （`git push origin --delete wip/tasks-<番号>-<時刻>`）。
2. backend と frontend の依存とテスト用の DB は、担当のワークフローが入れてある（backend は `python`、frontend は `frontend/node_modules` と Playwright の Chromium）。
   入れたのは master の版の依存のファイルからなので、1 のあと `git diff --name-only origin/master -- backend/requirements*.txt frontend/package-lock.json`
   で作業ブランチとの違いを見る。backend のファイルが出たら `python -m pip install -q -r backend/requirements-batch.txt -r backend/requirements-dev.txt`、
   `frontend/package-lock.json` が出たら `npm ci --prefix frontend` と `npx --prefix frontend playwright install chromium` で入れ直す（作業の途中で
   依存のファイルを変えたときも同じ）。
3. issue の本文とコメント（`GH_TOKEN=$FLOW_BOT_TOKEN gh issue view <番号> -R ridecompass/ride-compass-tasks --json title,body,comments --jq '.title, .body, (.comments[] | "--- \(.author.login) \(.createdAt)", .body)'`。
   `--comments` は端末でない出力ではコメントだけを出し、本文を出さない。答えのコメント・やり直しなら前の Pull Request のコメントも）を読み、CLAUDE.md と規約のとおりに作る。
   - ユーザーの判断が要るところは.claude/skills/ask/SKILL.md「問い」の形で書いて `ask.js` で問い、そこで終える（答えは次の起動で拾われる）。
     作る前に、答えの無い判断（方針・見た目の案・本番への書き込み等）が残っていないかを見て、残っていれば問いに要る分だけを
     調べて（画面を撮る・件数を数える等）作らずに問う。
     書き込みを断られたファイルの変更は、`docs/conventions/flow.md`「担当が書けないファイル」のとおり開発機へ返す。
     答えの補足が問いや提案の直しを求めていたら、直して問い直す。前提（blocked by）が見送りで閉じていたら、進める前に問う。
   - 作る前に、自分の直す場所で開いた issue を探し、前後関係と組を張る。探した鍵は報告に書く（.claude/skills/file-issue/SKILL.md「前後関係と組」の「探す」）。
   - 完了の条件（マージのあとの残りも）に、開発機にしか無いもの（`docs/conventions/flow.md`「担当」の「開発機が要る作業」）でしか確かめられない行があれば、
     同じことをテスト DB・CI で確かめる形（前後の SQL 文の比べ・テストの期待値等）へ書き換え、経緯に書き換えた理由を書いて進める。
     書き換えると確かめる対象か範囲が狭まるなら書き換えず、`docs/conventions/flow.md`「担当」の「開発機が要る作業」のとおり対話作業の段階にして手放す。
   - 前の回の CI が落ちて戻ったタスク（作業ブランチの下書きの PR があり、先頭のコミットのチェックが落ちている）は、落ちたチェックの記録
     （`gh pr checks <番号> -R hidakagit/ride-compass`・`gh run view <id> --log-failed -R hidakagit/ride-compass`）と、変異テスト（Mutation PR）の
     生き残りの注記（下の5の「変異テスト」）を読んで直し、4 から続ける。直すものが無ければ（取り消しで終わった・GitHub Actions の障害でランナーが
     付かなかった等）、`gh run rerun <id> --failed -R hidakagit/ride-compass` で流し直して手放す。
   - 1つの Pull Request に収まらないと分かったら、.claude/skills/file-issue/SKILL.md「段階に分ける」のとおりに分けて終える（段階は次の起動から1件ずつ振り出される）。
   - マージ済みの Pull Request があって戻ってきたタスク（マージのあとの残り）は、残りを済ませて完了の条件にチェックを付ける。
     確かめの行だけが残れば、手放すとゲートが確かめの問いを出す（自分では問わない。本番の実物で確かめてほしいときは、手放す前に下の
     「本番に出てから問う」のとおり本番に出るのを待ち、ユーザーが見る版をコメントに書く）。
     残りが時間を待つものだけ（数時間後・翌日の観測、外部の公開の日など）で、今は済ませられないなら、待たずに着手可能日時を
     入れて終える（`field.js <番号> 着手可能日時 '<YYYY-MM-DD HH:MM>'`）。日時は、済ませられるようになる日本時間の時刻にする。
     issue へのコメントに、何をその日に済ませるかを書く。PR も問いも出さずに終えてよく、
     ゲートが未着手にする（未来の着手可能日時）。その日に振り出された担当は、残りを済ませたら欄を消す（`field.js <番号> 着手可能日時 消す`）。
     **本番に出てから問う**: 本番の実物（画面・API）で確かめてほしい確かめは、マージの版が本番に出てから手放す（ゲートが問う）。出たかを見る口は
     変更が届く側で決まる: frontend は `/api/version`、
     backend は `/health` の `commit`（宛先は docs/architecture/tech-stack.md「本番の宛先」。backend は、Pull Request の差分に
     `scripts/deploy_backend_gate.py: DEPLOY_PATHS` に当たるファイルがあるときだけ見る）。`git merge-base --is-ancestor <マージのコミット> <本番の commit>`
     が 0 で終われば出ている（本番の commit が手元に無ければ先に `git fetch origin`）。
     出ていなければ、master の CI の一番新しい実行（`gh run list -R hidakagit/ride-compass --workflow ci.yml --branch master --limit 1 --json databaseId,headSha`）を
     `gh run watch <id> --compact -i 30 -R hidakagit/ride-compass --exit-status` で終わるまで前に出したまま待ってから見直す（Bash の `timeout` を上限の 600000 にして打ち、上限で止まったら同じコマンドを打ち直す。裏へ回さない）。まだ出ていなければ、同じ `gh run list` で一番新しい
     実行を引き直し、待った実行と違えばそれを同じく待って見直す（master の CI は待ちを一番新しい1件だけにし、新しい実行が来ると古い待ちを
     取り消す。`.github/workflows/ci.yml` の `concurrency`）。待ち直す回数に上限は置かない（押されて取り消された待ちには、押した新しい実行が
     必ずあり、master へのコミットが止まれば終わる。外の上限は担当のジョブの持ち時間）。
     マージのコミットを含む実行（`headSha` がマージのコミットかその後の版）のうち一番新しいものが終わっても出ておらず（失敗・取り消し）、
     それより新しい実行が無いときだけ、上の時間を待つ残りと同じく着手可能日時を翌日にして終える。
     出たら、ユーザーが見る版をコメントに書いてから手放す。frontend に届く変更は「画面右上のメニュー（︙）の『バージョン表示』の版が <見た時点の
     本番の `commit` の頭8文字> なら修正を含む版。違えば、それより後の版が出ていて、それも修正を含む」、backend にだけ届く変更は
     開く URL と見た時点の `started_at`（「`started_at` がこの時刻以降なら修正を含む版」）。

     残りが無くなれば手放す（ゲートが、チェックの残りが無いことを見て完成で閉じる）。
   - 段階に分けた親が、段階が全部閉じて振り出されたら、段階でまだ確かめていない親の完了の条件を確かめてチェックを付け、手放す。
   - コードを変えないタスク（調査・見積もり・計測）は、結果を本文に書いて自分の分の完了の条件にチェックを付け、結果を確かめてもらう行
     （`- [ ] ユーザーが確かめる: <結果の何を>`）を足して手放す（ゲートが確かめの問いを出し、完了はユーザーの答えで決まる）。
   - 確かめの答えで足された `- [ ] 直す: …` の行（ユーザーが「よくない」とした項目）は、ほかの残りと同じく済ませてチェックを付ける。
4. `tasks#<番号>:` の件名でコミットし、`git push origin orch/tasks-<番号>` で push する。push はほかのコマンドとつながずに1つで打つ
   （拒否の一覧の `Bash(git push *master*)` はつないだ全文に当たり、後ろの `gh pr create --base master` 等の `master` でも断る）。静的検査とテストを手元で回す場面と範囲と、
   コミットの前に frontend で変えたファイルへかける整形は、.claude/skills/run-checks/SKILL.md「手元の検査の回し方」だけが決め、全体は CI に任せる。作業ブランチの強制 push は
   コードのリポジトリの規則で断られるので、直しは足すコミットにする。
   master に入るコミットは、5 の Pull Request の題名と本文から作られる（確かめる担当が squash でマージする）。CI は 5 の
   Pull Request の実行だけを待つ（作業ブランチへの push で走るかは .claude/skills/run-checks/SKILL.md「検査の置き場（手元・作業ブランチのCI・masterのCI）」）。
5. マージの前に済ませる本番への書き込みが要り、まだ済んでいなければ、`docs/conventions/flow.md`「担当」の「自動で進めないもの」のとおり返す。
   コードのリポジトリに Pull Request を下書きで出す（`gh pr create --draft --base master --head orch/tasks-<番号>`。
   hidakagit の名義で打つ。担当は gh の既定（`GH_TOKEN`）が `CODE_TOKEN`
   （`docs/conventions/flow.md`「担当」の「名義」）、開発機の対話のセッションは gh のログインのままでよい）。
   題名と本文は、そのまま master のコミットになる（`docs/conventions/flow.md`「コミット」）。本文は `.github/pull_request_template.md`
   を作業ツリーの外へ写し、各節の `<…>` をその節に書くものへ置き換えて作る（節の外の行を最初の節より前に足さない）。
   `node tools/flow-gate/bin/pr-body.js <本文のファイル>` で形を照らしてから `--body-file <本文のファイル>` で渡す（`gh pr create` の
   `--template` は `--body-file` と併せられず、手で書く画面の下書きにしか使えない）。形に沿わない本文は Pull Request の CI
   （Claude Gate の flow-gate）が落とす。検証の節には、下の確かめ方も書く。
   画面に届く変更は、後からの判断の記録として、修正が波及する範囲（変えたコード——部品・hooks・backend の応答等——を使う・見せる画面と状態のすべて）を漏らさず撮り、
   修正前後のキャプチャを Pull Request のコメントに貼る（`node tools/flow-gate/bin/attach.js <Pull Request の番号> '<画像>#<見出し>' ...`。
   見出しに画面・幅など、何を撮ったかを書く。下の「貼り方」。画像はコミットに残さない）。画面は `node frontend/scripts/capture.mjs --script <脚本>` で撮る
     （開く版を `--app`、応答を `--api` で選び、見せたい状態までは脚本で進める。脚本の口と使い方はスクリプトの先頭、例は
     `frontend/capture/examples/`。脚本は作業ツリーの外に置いてよい。外に置いた脚本は確かめる担当に届かないので、キャプチャの
     あとのコメントに、`<details>` で畳んだコードの囲みで脚本の全文と打った `capture.mjs` の引数を貼る。脚本は何も読み込まないので、モックへ
     足した応答も脚本の `patch` ごと貼れる）。前は本番を撮り（`--app production`。ビルドしない）、後は
     `--api <本番の backend>`（作業ツリーの版を手元でビルドし、本番の backend へ向ける。宛先は docs/architecture/tech-stack.md「本番の宛先」）で、
     前と同じ脚本で撮る。backend の応答も変わる変更は、変わる経路が DB を読まない（タイルの中継等）なら
     `--backend <パスの頭>`（例: `--backend /api/jma-tile/`）でその経路だけを作業ツリーの backend に返させ、DB を読む経路なら変わる応答を脚本の `patch`
     （JSON の応答だけ。本番の backend にまだ無い経路も）で差し替えて後を撮る。
     本番で開けない画面（認証の要る管理画面等）は、e2e のモックの応答（既定）で、前は `--app origin/master`、後は既定の作業ツリーの版で撮る。
     管理画面は脚本の口 `openAdmin` で開く（撮影用の資格情報は `capture.mjs` が渡すので、環境変数は要らない。管理APIの応答は口の `routes` で差し替える）。
     本番の版（`/api/version` の `commit`）と作業ブランチの合流点
     （`git merge-base HEAD origin/master`）の間で frontend が変わっていて（`git diff --name-only <本番の commit> <合流点> -- frontend`）、
     それが撮る画面に関わるなら、前は本番の代わりに `--app <合流点> --api <本番の backend>` で撮る。
     **貼り方**: `attach.js` は画像を1枚ずつ別のコメントで貼り、貼れなければそこで止まって、出た文言とそれまでに貼った分を出す。
     名義の誤りで止まったら `GH_TOKEN` を見直す。ほかの文言で止まったら、出た行を 6 の報告に書いて進める。
     画面に出ない変更は、確かめ方と根拠（実行したコマンドと出た値・読んだ公式の文書）を検証に書く。
   Pull Request の題名・本文・コメントには、打ったコマンドを写すときも本番の宛先の値を書かず、
   `--api <本番の backend>` のように tech-stack.md「本番の宛先」の名で書く（値を含む書き込みは、自動モードの判定に
   `[Excess Sensitive Detail]` で断られうる。`--attach` の付いた書き込みそのものは断られない）。
   前の Pull Request が開いたまま残っていれば、新しく出さずに push し、撮り直したキャプチャを `attach.js` で足す。
   本文を直すときは `gh issue edit <番号> -R hidakagit/ride-compass --body-file <ファイル>` で書き換える（直すと CI が形を照らし直す。`gh pr edit` と、欄を選ばない
   `gh pr view` は、組織を読む権限の無いトークンでは断られる）。
   CI は待たない（下書きのまま push したら手放す。CI が通るとゲートが PR をレビュー可能にして確かめる担当へ渡し、落ちたら作る担当が
   もう一度振り出される）。手元で回す検査は .claude/skills/run-checks/SKILL.md「手元の検査の回し方」が決める。
   **変異テスト**: `backend/app` を変えたときは、必須でないワークフロー Mutation PR（`.github/workflows/mutation-pr.yml`）も走り、変えた関数の変異のうち
   テストが気づかないもの（生き残り）を、変えた行への注記（`gh run view <id> -R hidakagit/ride-compass` の ANNOTATIONS）と実行の要約に出す。
   前のコミットの回に無かった生き残りの注記があると、ゲートは落ちたものと同じに扱う。戻ってきた回に生き残りを読み、利用者や運用に見える
   振る舞いが変わるものは、それを落とすテストを足す（足すかの判断は .claude/rules/testing.md「そのテストは要るか」）。足さないもの
   （振る舞いが変わらない書き換え・テストで確かめない約束）と、変わったのにどのテストも通らない関数は、Pull Request の本文の検証に1件1行で
   理由を書く（同じ注記は次の回に前の回と同じものとして通る）。
6. issue の本文を直し（経緯・完了の条件のチェック。マージのあとでないとできない条件だけをチェックの無いまま残す）、
   何をしたか・何が残っているかと Pull Request へのリンクを issue と Pull Request のコメントに書いて報告し、手放す（次の担当が同じ枝と PR から続ける）。

**Pull Request のあと**（ゲートが、コードのリポジトリの Webhook から届く PR・CI の実行の出来事で決める）
- コードのリポジトリは、master に入れる前に必須チェック（名前は docs/architecture/tech-stack.md「CIの実行枠（リポジトリがpublicである間の前提）」）が Pull Request で通ることを
  求める（ルールセット。管理者にも効く）。最新の master の取り込みは求めない。それぞれ通った Pull Request の組み合わせで壊れたものは
  master の CI が捕まえ、通るまで本番へは出ない（`ci.yml` の `deploy-backend`・`deploy-frontend`）。落ちた知らせは GitHub の通知（Actions の失敗）で
  hidakagit に届き、直すのは普通のタスクにする。
- PR と CI の事実からのステータスの決め方は `docs/conventions/flow.md`「ステータスと割り当て」が持つ。ゲートが出来事を受け損ねても、見回りの
  突き合わせが次の周で決め直させるので、担当は動かさない。

**確かめる担当**（検証待ちから振り出され、持つと検証中。作った担当とは別）
1. 作業ブランチを取る（`git fetch origin` と
   `git checkout -B orch/tasks-<番号> origin/orch/tasks-<番号>`）。依存のファイルが master と違えば、作る担当の2のとおり入れ直す。Pull Request（`gh pr view <番号> -R hidakagit/ride-compass --json title,body,comments,reviews`。本文のキャプチャ・差分）・Pull Request の CI・issue の完了の条件・変更が届く範囲（要るなら画面）を
   確かめる。作る担当の報告を読み写さず、自分で見る（画面なら変更後を自分で撮る。作る担当の5と同じ道具・脚本・応答で撮り、
   変更前は撮り直さずに作る担当が貼った画像と比べる。作る担当がコメントに脚本を貼っていれば、作業ツリーの外へ写して同じ引数で撮る）。
   貼った画像は、`gh api repos/hidakagit/ride-compass/issues/<Pull Request の番号>/comments --jq '.[].body'` で添付の URL
   （`https://github.com/user-attachments/assets/…`）を拾い、`curl -sSL -o <作業ツリーの外のファイル> <URL>` で取り出して Read で見る。
   添付は認証なしで取れるので、トークンを付けない。CI は待たない（必須のチェックが全部通ったのを見て、ゲートが検証待ちにしている）。
   `lost_constraints.py` も自分で回し、
   「消えた」制約に本文の処置が無ければ満たしていない。
   確かめるのは、完了の条件と、変更が届く利用者に見える結果（画面・API の応答・テストが見る振る舞い）を先にする。
   **書き込みのある道具を流す**: 本物の GitHub へ書く道具（`tools/flow-gate/bin/`）の振る舞いは、写しを作って書き込みを差し替えずに、
   道具の試しの形（`--dry-run`）で流す。試しを持つ道具は使い方の1行に `[--dry-run]` を書いてあり、持たない道具は `--dry-run` を断って
   何もせずに終える（`tools/flow-gate/bin/cli.js: args`）。後始末（`after.js`）の実行のファイルは、確かめたい終わり方の発言の並び
   （例: 利用の上限の `error` を持つ発言）を作業ツリーの外に書いて渡す。試しは本物の状態を読み、止める時刻・動かす遷移・書くはずの
   コメントを「（試し）」と出すだけで書かない。試しを持たない道具と、書く呼び出しそのもの（リポジトリの変数の PATCH・POST 等）は、
   試しの形では通らないのでコードを読んで見る。
2. 確かめた結果を、満たしていてもいなくても issue にコメントで書く（見出し「確かめた結果」）。完了の条件の1件ごとに、
   何をどう見て（実行したコマンド・開いた画面）何が出たかを書き、撮った画面は Pull Request へ `attach.js` で貼る
   （貼り方と貼れないときの扱い・添える説明の中の本番の宛先は、作る担当の5と同じ）。
3. ユーザーが見るべきだと判断したら（利用者から見える振る舞い・モジュールの設計が変わる等）、完了の条件に確かめてもらう行
   （`- [ ] ユーザーが確かめる: …`）を足し、理由を書く。マージは確認を待たない。ただし issue の答えがマージの前にユーザーの確認を
   求めていて、その確認の答えがまだ無ければ、マージせずに確認を `ask.js` で問い、Pull Request はレビュー可能のまま残す（答えの範囲を
   広げて読まない。.claude/skills/ask/SKILL.md「答え」）。続けるの答えが返ると、ゲートが検証待ちにし、次の確かめる担当がマージする。
   マージしたあと、残りがユーザーの確かめの行だけなら、手放すとゲートが確かめの問いを出す（作る担当を起こし直さない）。本番の実物で
   確かめてほしいときは、作る担当の3の「本番に出てから問う」のとおり、本番に出てから版をコメントに書いて手放す。
   残りが開発機にしか無いもの（`docs/conventions/flow.md`「担当」の「開発機が要る作業」）で確かめる行だけなら、マージのあとで対話作業の段階にする。
   **作る担当の着手より後に届いた依頼**: issue のコメントを読み、作る担当の着手より後に届いた
   依頼（ほかのタスクの担当からの申し送り等）のうち完了の条件に
   無いものは、本文の完了の条件へチェックの無い行として足し、2 の結果にどのコメントから足したかを書く。足した行は差し戻す理由に
   しない（4 の「満たしていない」には当てない）。マージすると残りとして未着手になり、作る担当がマージのあとの残りとして済ませる。
4. 1 で「満たしていない」とした条件のどれかに当たれば、足りないことを Pull Request のコメントに書いて下書きへ戻す（差し戻し。
   `gh pr ready <番号> -R hidakagit/ride-compass --undo`）。戻ったかは `gh pr view <番号> -R hidakagit/ride-compass --json isDraft` で
   `true` が出るかで見る。手放すとゲートが未着手にし、作る担当が同じ枝と PR で直す。それ以外の気づき（本文の数字の誤り・書き漏れ・使われない import 等）は閉じる理由にせず、2 の結果に書く。
   そのうち Pull Request の範囲の中で master に残るもの（差分が変えたものを書いたまま直し漏れた文書の行・使われない import 等）は、
   3 の「着手より後に届いた依頼」と同じく本文の完了の条件へチェックの無い行として足し、2 の結果に足したことを書く（マージすると
   残りとして未着手になり、作る担当が済ませる）。master に残らないもの
   （Pull Request の本文の数字の誤り等）は、結果に書くだけでよい。Pull Request の範囲の外のものは、上の「範囲の外の気づき」のとおり行き先か直さない理由を付けてから 5 へ進む。
5. 満たしていれば、マージの前に、1 で確かめて満たしていた完了の条件へ issue の本文でチェックを付ける（本文をファイルに書いて
   `GH_TOKEN=$FLOW_BOT_TOKEN gh issue edit <番号> -R ridecompass/ride-compass-tasks --body-file <ファイル>` で書き戻す）。作る担当が付け漏らした条件・
   開発機の対話のセッションで出た Pull Request の条件も、ここで付ける。
   付けないのは、確かめの行（`- [ ] ユーザーが確かめる: …`）・マージのあとでないとできない条件・3 と 4 で足した行。4 で閉じるときは
   どの行にも付けない。
   **マージの前の本番の値**: マージすると本番へ自動で出て前の版が消えるので、完了の条件に本番での前後の比べ（.claude/rules/fixing.md「性能は本番で測る」等）が
   残っていて、今の本番の版で取った前の値が issue に無ければ、マージの前に取る。本番を読むだけの口（書き込まない要求で画面・API を外から通す。
   `scripts/prod_route_check.py` と同じ口）で、その行と同じ要求・同じ測り方で取り、値・要求・取った時点の本番の版（作る担当の3の「本番に出てから問う」と
   同じ口の `commit`）を issue にコメントで書いてからマージする。読むだけの口で取れない（本番の DB・ログが要る）なら、マージせずに、要る前の値と
   取り方を書いた対話作業の段階を起こし（`docs/conventions/flow.md`「担当」の「開発機が要る作業」）、Pull Request はレビュー可能のまま残す
   （段階が閉じると、ゲートが検証待ちにし、次の確かめる担当がマージする）。
   そのあと Pull Request を squash でマージする（`gh pr merge <番号> -R hidakagit/ride-compass --squash`）。CI は通ったのを見てゲートが渡しているので、待たずに打つ。master の CI も
   待たない（手放すと、ゲートが残りで決める）。通ったかは
   `gh pr view <番号> -R hidakagit/ride-compass --json state` で `MERGED` が出るかで見て、`OPEN` のままなら打ち直す。
6. master と競合してマージできなければ、`git fetch origin` で今の master を取ってから
   `git -c merge.conflictStyle=diff3 merge origin/master` で取り込み（`diff3` は競合の塊に合流点の行を `|||||||` の下に出す）、
   競合の塊ごとに、合流点の行を両側がどう変えたかで解き方を決める（確かめる担当が push した版は CI が通っていないので、push したら
   マージせずに手放す。ゲートが CI の終わりを待って検証待ちに戻し、次の確かめる担当がマージする）。
   - 合流点の行を変えたのが片側だけ: 変えた側を採る。
   - 両側が変えたが、合流点のどの行も片側だけが変えている（両側が足した行・変えた行が隣り合っているだけ）: 両側の変えた行を、
     どれも書き換えずに合流点での並びのまま残す。
   - 合流点の同じ行を両側が変えた・消した: 新しい行を書かないと解けない。

   どの塊も上までで解けたら、「競合を解く」のとおりに解き、下書きへ戻してから（`gh pr ready <番号> -R hidakagit/ride-compass --undo`）
   `git push origin orch/tasks-<番号>` で push して手放す（並べたことで壊れたものは必須のチェックで見る）。新しい行を書かないと解けない塊が1つでもあれば、
   `git merge --abort` で戻し、どのファイルのどこが重なったかを書いて「競合」として差し戻す（4 と同じ。作る担当が取り込んで直す）。

**競合を解く**（作る担当の 1・確かめる担当の 6）: 競合したファイルを開き、`<<<<<<<`・`|||||||`・`=======`・`>>>>>>>` の印と
残さない行（`diff3` なら合流点の行も）を編集で消してから `git add <ファイル>` と `git commit --no-edit`。git checkout の `--ours`・`--theirs` は使わない。

# タスクの流れの仕組み

[flow.md](../conventions/flow.md) の決まりを動かす仕組み。ゲート・道具は `tools/flow-gate/`、担当と見回りは `.github/workflows/` にある。

## 構成

| 部品 | 置き場 | すること |
|---|---|---|
| ゲート | Cloudflare Worker `ridecompass-gate`（`src/gate.js`） | 置き場とコードのリポジトリの Webhook を受け、遷移の表（`flow.config.json: transitions`、照らしは `src/rules.js: judge`）でステータスを書き、担当者・本文の先頭のボタン・回答待ちの問いをそろえる。表に無い変化を戻す。自分の書き込みは無視する |
| 回答フォーム | Cloudflare Worker `ride-compass-answer`（`src/form.js`。Cloudflare Access の内側） | 最新の問いを出し、答えを hidakagit の名義で書いてステータスを動かす |
| 見回り | `claude-dispatch.yml` が `bin/dispatch.js` を `coordinator.watchEveryMinutes` ごとに打つ | 振り出せるタスク（`src/dispatch.js: ready`）を、種類ごとの枠（`coordinator.slots`）まで担当のワークフローへ起こす。Project の「状況の更新」を書く |
| 担当のワークフロー | `claude-task.yml`（実行の名前は「#<番号> <種類>」） | 1件を引き受け、準備し、担当（`anthropics/claude-code-action`）を起こし、後始末をする。番号ごとの `concurrency`（`queue: max`）で、同じタスクの実行は1本ずつ動く |

## 担当のワークフローの1回

1. **引き受ける**（`bin/claim.js`）: 作るなら未着手 → 進行中へ動かせたとき、確かめるなら検証中のときだけ進み、着手のコメントを書く。種類「開発機」は担当を起こさず、`hold.js` が手放すまで番号を持つ。
2. **準備**: PostgreSQL + PostGIS・backend と frontend の依存・Playwright の Chromium・`poppler-utils` を入れ、権限（下の「権限」）を渡す。
3. **担当を起こす**: 指示は役・issue の番号・読む文書だけを渡す。担当は手番を終えた最初の発言で終わるので、裏で動かす道具（`run_in_background`・Monitor・ScheduleWakeup・cron・Workflow）は外してあり、待つときは前に出したまま待つ。持ち時間はジョブの `timeout-minutes`。
4. **後始末**（`bin/after.js`。担当が落ちても走る）: GitHub に無い変更を `wip/tasks-<番号>-<時刻>` の枝へ残す。作る担当のタスクが進行中のままなら、理由を書いて未着手へ戻す。Claude の利用の上限・認証で止まったら、変数 `coordinator.pauseVariable` に時刻を置いて振り出しを `coordinator.pauseMinutes` 止める。最後に、担当の最後の発言・後始末がしたこと・判定に断られた操作・実行へのリンクを、終わりのコメントとして issue に書く。

## 見回り

- 実行ごとに master の今の道具を取り出し直して1周打つ。`coordinator.watchForMinutes` が過ぎたら、次の実行を起こしてから終える。
- 1周の失敗では止まらず、`coordinator.watchFailMinutes` のあいだ1周も通らなければ失敗で終わる（GitHub の失敗の知らせが届く）。途切れたら `gh workflow run claude-dispatch.yml -R hidakagit/ride-compass` で起こし直す。
- 状況の更新（`src/dispatch.js: summary`）には、動いている担当・振り出しを待つ仕事の数と、気づくべきもの（進行中なのに動いている担当が無いタスク・振り出せる仕事があるのに空いた枠・落ちた実行）を書く。どれかがあれば At risk。
- `node tools/flow-gate/bin/dispatch.js --dry-run` で、何を起こし何を書くかを書かずに見られる。
- **止める**: Actions の画面で Claude Dispatch を Disable workflow（戻すときは Enable workflow のあと Run workflow）。1件だけ止めるなら、ボードで保留へ動かす。

## 道具

流れの道具（`tools/flow-gate/bin/`）は、作業ツリーの版が `origin/master` と違えば master の版を取り出して打つ（`bin/cli.js`）。`--dry-run` を持つのは `move.js`・`after.js`・`dispatch.js` で、作業ツリーの版で書かずに動く。

| 道具 | すること |
|---|---|
| `move.js <番号> <行き先> [理由]` | 理由をコメントに書き、表で照らしてステータスを動かす |
| `ask.js <番号> <ファイル>` | 問いの形を照らしてコメントに置き、回答待ちへ動かす。落ちたら同じファイルで打ち直す |
| `field.js <番号> [欄 値]` | Project の欄（優先度・着手可能日）を読み書きする。入っている優先度は書き換えない |
| `stage.js <親> <題名> <ファイル> [前の段階...]` | 段階を親付きで作り、前の段階と親に blocked by を張る |
| `hold.js <番号> [--release <id>]` | 開発機の対話のセッションが種類「開発機」の実行で番号を持つ・手放す |
| `attach.js <PR> '<画像>#<見出し>' ...` | PR へ画像を1枚ずつ貼り、貼れなければ止まる |
| `claim.js`・`after.js`・`dispatch.js` | 担当のワークフローと見回りが打つ |
| `settings.js` | 開発機のセッションの始まりに、権限をユーザー設定へ写す |

## 名義

置き場へは hidakagit-bot（`FLOW_BOT_TOKEN`）、コードのリポジトリへは hidakagit（`CODE_TOKEN`。マージで master の CI とデプロイが起きる）、
Claude は契約のトークン（`CLAUDE_CODE_OAUTH_TOKEN`）。担当のワークフローは gh の既定に `CODE_TOKEN` を置き、これは置き場に届かない。
どのトークンがどこへ届くかは [tech-stack.md](tech-stack.md)「秘密の値とトークン」。

## 権限

`tools/flow-gate/settings.json` の master の版が、担当と開発機のセッションの両方の権限を決める（担当は連携の `settings`、開発機は
`SessionStart` のフックの `settings.js` がユーザー設定へ写す。変更は master に入った次のセッションから効く）。

- `permissions.defaultMode` は `auto`。判定役には `autoMode` で環境と日常の操作を教える（公式「Configure auto mode」）。各一覧は `$defaults` を残す。
- 打たせない操作（master への push・強制の push・`gh api` の書き込み・`gh workflow`・`gh secret`・`gh variable` 等）は `permissions.deny` で断る。
  規則はコマンドの文に当てるので、読むだけでも `-X`・`-f` の付いた `gh api` は断られる。読むときは欄を URL に書くか、`gh run list`・`gh issue view --json` を使う。
- 日常の操作が断られたら、回り込まず `autoMode` の説明を直す。断られた操作は、後始末の終わりのコメントの「判定に断られた操作」に出る。

## 変える・公開する

- 遷移の表・ゲートが置く問いの文・枠は `flow.config.json` を直す。
- テストは `node --test tools/flow-gate/test/*.test.js`、構文と import は `tools/flow-gate` で `npm ci` のあと `npm run lint`。CI（`claude-gate.yml` の `flow-gate`）も同じ2つを流す。
- master に入ると `claude-gate.yml` の `deploy-gate` が `wrangler deploy`（Webhook）と `wrangler deploy --env form`（回答フォーム）で公開する。ゲートは出来事が届いた issue から今の規則の姿へ書き直す。

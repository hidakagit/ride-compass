// ゲートを公開の入口（index.js の fetch）で確かめる。差し替えるのは GitHub（網）だけ。
import assert from "node:assert/strict";
import { before, test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import worker from "../src/index.js";
import { adoptionQuestion, formChoices, parseQuestion, whatQuestion } from "../src/rules.js";
import { fakeGitHub } from "./fake-github.js";

const env = { APP_ID: "1", WEBHOOK_SECRET: "secret", FORM_TOKEN: "form-token", CODE_TOKEN: "code-token" };
const [ME, BOT] = [config.people.hidakagit.id, config.people["hidakagit-bot"].id];

before(async () => {
  const { privateKey } = await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign"]);
  env.APP_KEY = `-----BEGIN PRIVATE KEY-----\n${Buffer.from(await crypto.subtle.exportKey("pkcs8", privateKey)).toString("base64")}\n-----END PRIVATE KEY-----`;
});

async function deliver(event, payload, secret = env.WEBHOOK_SECRET) {
  const body = JSON.stringify({ installation: { id: 7 }, sender: { login: "hidakagit" }, ...payload });
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = Buffer.from(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body))).toString("hex");
  const waits = [];
  const res = await worker.fetch(
    new Request("https://gate.test/webhook", { method: "POST", body, headers: { "x-github-event": event, "x-hub-signature-256": `sha256=${sig}` } }),
    env, { waitUntil: (p) => waits.push(p) });
  await Promise.all(waits);
  return res;
}
const item = (extra) => ({ projects_v2_item: { content_type: "Issue", project_node_id: "PVT_1", content_node_id: "I_1" }, ...extra });
const move = (from, to) => deliver("projects_v2_item", item({ action: "edited", changes: { field_value: { field_node_id: "F_1", field_name: "Status", from: from && { name: from }, to: { name: to } } } }));
const comments = (gh) => gh.writes.filter((w) => w.op === "addComment").map((w) => w.body);

test("署名が合わない出来事は受けず、何も書かない", async () => {
  const gh = fakeGitHub({ issue: { number: 1, authorId: ME } });
  assert.equal((await deliver("projects_v2_item", item({ action: "created" }), "wrong")).status, 401);
  assert.deepEqual(gh.writes, []);
});

test("秘密の値を持たない口は開けない（Webhook の Worker に回答フォームは無く、回答フォームの Worker に Webhook は無い）", async () => {
  fakeGitHub({ issue: { number: 1, authorId: ME } });
  const { FORM_TOKEN, WEBHOOK_SECRET, ...bare } = env;
  assert.equal((await worker.fetch(new Request("https://gate.test/answer?issue=1"), { ...bare, WEBHOOK_SECRET })).status, 404);
  assert.equal((await worker.fetch(new Request("https://gate.test/webhook", { method: "POST", body: "{}" }), { ...bare, FORM_TOKEN })).status, 404);
});

test("ゲート自身が起こした出来事は捨てる", async () => {
  const gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "保留" } });
  await deliver("projects_v2_item", item({ action: "edited", sender: { login: config.gate }, changes: { field_value: { field_node_id: "F_1", from: { name: "保留" }, to: { name: "進行中" } } } }));
  assert.deepEqual(gh.writes, []);
});

test("入口: hidakagit が書いた issue と段階（親のある issue。採否は親で済んでいる）は未着手で Claude に、ほかの人のものは回答待ちで hidakagit に割り当て、採否の問いを本文に置く（コメントは書かない）", async () => {
  let gh = fakeGitHub({ issue: { number: 1, authorId: ME } });
  await deliver("projects_v2_item", item({ action: "created", sender: { login: "github-project-automation[bot]" } }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", ["hidakagit-bot"]]);
  assert.equal(gh.issue.body ?? "本文", "本文");
  assert.deepEqual(gh.issue.fields, config.project.defaults, "欄の既定値（優先度など）が入る");

  gh = fakeGitHub({ issue: { number: 2, authorId: BOT } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["回答待ち", ["hidakagit"]]);
  assert.deepEqual(comments(gh), []);
  assert.ok(gh.issue.body.startsWith(`<!-- flow-gate -->\n<!-- 問い\n${adoptionQuestion(config).trim()}\n-->\n`));

  gh = fakeGitHub({ issue: { number: 3, authorId: BOT, parent: { number: 1 } } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", ["hidakagit-bot"]]);
});

test("表にある移動は通して既定の割り当てを書き、表に無い移動は戻して理由を書き、ボードで完了にしたら見送りで閉じる", async () => {
  let gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "未着手", assignees: ["hidakagit"] } });
  await move("保留", "未着手");
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", ["hidakagit-bot"]]);

  gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "進行中", assignees: ["hidakagit-bot"] } });
  await move("保留", "進行中");
  assert.equal(gh.issue.status, "保留");
  assert.match(comments(gh)[0], /「保留」から「進行中」へは動かせません.*「保留」へ戻しました/);

  gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "回答待ち", assignees: ["hidakagit"] } });
  await move("保留", "回答待ち");
  assert.equal(gh.issue.status, "保留", "保留から回答待ちへはボードで動かせない（問いは未着手に戻してから Claude が書く）");

  gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "完了" } });
  await move("保留", "完了");
  assert.equal(gh.issue.state, "CLOSED");
  assert.deepEqual(gh.writes.find((w) => w.stateInput).stateInput, { value: "CLOSED", stateReason: "NOT_PLANNED" });
});

// bin/ask.js が書いたのと同じ、本文の先頭に画面に出ない形で問いを置いた本文。
const asked = (q) => `<!-- flow-gate -->\n<!-- 問い\n${q}\n-->\n<!-- /flow-gate -->\n\n本文`;
// 回答フォームを開く（本文の先頭のボタンと同じ入口）・選択肢の番号を文で引く・送る。
const openForm = (number) => worker.fetch(new Request(`https://gate.test/answer?issue=${number}`), env);
const choiceOf = (html, text) => [...html.matchAll(/name="choice" value="(\d+)"[^>]*data-text="([^"]*)"/g)].find((m) => m[2] === text)?.[1];
async function send(html, fields, labels = []) {
  const form = new FormData();
  const [issue, q] = [/name="issue" value="(\d+)"/, /name="q" value="([^"]+)"/].map((r) => r.exec(html)[1]);
  Object.entries({ issue, q, note: "", ...fields }).forEach(([k, v]) => form.set(k, v));
  for (const l of labels) form.append("label", l);
  return (await worker.fetch(new Request("https://gate.test/answer", { method: "POST", body: form }), env)).json();
}

test("回答フォーム: 表で行ける選択肢だけを出し、答えは hidakagit の名義で問い・選択肢・判断材料ごと1つに残し、ステータスと割り当てはゲートが書き、本文の先頭の問いを消す", async () => {
  const q = "## 問い\n手順はどちらにしますか？\n\n### 選択肢\n- A 案 → 未着手\n- 私がやる → 未着手 / hidakagit\n- 進める → 進行中\n\n<details><summary>判断材料</summary>\n材料の文\n</details>";
  const gh = fakeGitHub({ issue: { number: 4, authorId: ME, status: "回答待ち", assignees: ["hidakagit"], body: asked(q) } });
  const html = await (await openForm(4)).text();
  assert.match(html, /A 案/);
  assert.doesNotMatch(html, /進める/);
  assert.match(html, /<div class="cols"><details><summary>判断材料<\/summary><div class="md"><p>描いた: 材料の文<\/p><\/div><\/details><form>/,
    "判断材料は GitHub の描き方で出し、PC の幅で左右に並べる箱に入れる");

  const before = gh.requests.length;
  const r = await send(html, { choice: "1", next: "hidakagit" });
  assert.deepEqual(gh.requests.slice(before), ["読む", "addComment", "updateProjectV2ItemFieldValue+updateIssue"],
    "送信は、読む・答えを書く（1個）・決定を書く（ステータスと issue の更新の2個）だけ");
  assert.equal(r.label, "私がやる");
  const answer = gh.writes.find((w) => w.op === "addComment");
  assert.equal(answer.as, "hidakagit");
  assert.equal(answer.body, `## 回答\n**手順はどちらにしますか？**\n\n○ A 案\n● **私がやる**\n${config.formOptions.map((o) => `○ ${o.text}`).join("\n")}\n\n` +
    "次のステータス: 未着手\n次に動くのは: hidakagit\n\n<details><summary>判断材料</summary>\n\n材料の文\n</details>");
  assert.deepEqual([gh.issue.status, gh.issue.assignees, gh.issue.body.includes("<!-- 問い")], ["未着手", ["hidakagit"], false]);
});

test("判断材料を GitHub で描けないときは、判断材料の文字をそのまま出す", async () => {
  fakeGitHub({ markdown: false, issue: { number: 4, authorId: ME, status: "回答待ち", assignees: ["hidakagit"],
    body: asked("## 問い\nどうする？\n\n### 選択肢\n- A → 未着手\n- B → 保留\n\n<details><summary>判断材料</summary>\n**太字** と <b>タグ</b>\n</details>") } });
  assert.match(await (await openForm(4)).text(), /<div class="plain">\*\*太字\*\* と &#60;b&#62;タグ&#60;\/b&#62;<\/div>/);
});

test("問い直し: 答えて Claude の番になると回答フォームは開かず、Claude が問いを書いて hidakagit に割り当てると、本文の先頭の問いの下にボタンが出る", async () => {
  const gh = fakeGitHub({ issue: { number: 5, authorId: BOT, status: "回答待ち", assignees: ["hidakagit-bot"] } });
  const closed = await openForm(5);
  assert.deepEqual([closed.status, (await closed.text()).includes("いまは Claude の番です")], [404, true]);

  const q = "## 問い\n新しい問い？\n\n### 選択肢\n- A → 未着手\n- B → 保留";
  Object.assign(gh.issue, { body: asked(q), assignees: ["hidakagit"] });
  await deliver("issues", { action: "assigned", issue: { node_id: "I_1" } });
  assert.ok(gh.issue.body.startsWith(`<!-- flow-gate -->\n<!-- 問い\n${q}\n-->\n[![`) && gh.issue.body.includes("**回答待ち**: 新しい問い？"));
  assert.match(await (await openForm(5)).text(), /新しい問い？/);
  await deliver("issues", { action: "labeled", issue: { node_id: "I_1" } });
  assert.equal(gh.writes.filter((w) => w.op === "updateIssue" && "body" in w).length, 1, "本文の先頭が今の状態と同じなら書き直さない");
});

test("回答フォームは置き場のラベルを全部、今の付き方のまま並べ、付け外しがそのまま効いて答えに残る（Project の欄は出さない）", async () => {
  const gh = fakeGitHub({ issue: { number: 7, authorId: BOT, status: "回答待ち", assignees: ["hidakagit"], labels: ["規模S"], fields: { [config.project.priorityField]: "中" }, body: asked(adoptionQuestion(config).trim()) } });
  const html = await (await openForm(7)).text();
  assert.doesNotMatch(html, /name="field:/, "Project の欄は機械が決めるので出さない");
  assert.match(html, /name="label" value="規模S" checked/);
  assert.match(html, new RegExp(`name="label" value="${config.project.urgentLabel}">`));
  await send(html, { choice: "0", next: "hidakagit-bot" }, [config.project.urgentLabel, config.verify.label]);
  assert.deepEqual(gh.issue.labels.sort(), [config.project.urgentLabel, config.verify.label].sort());
  assert.match(comments(gh)[0], new RegExp(`\nラベル: \\+${config.project.urgentLabel} \\+${config.verify.label} −規模S$`));
  assert.deepEqual(gh.issue.fields, { [config.project.priorityField]: "中" }, "回答フォームは欄を変えない");
});

test("採否の問い（入口で本文に置いたもの）に答えると、採否の問いと選択肢ごと答えに残り、やらないなら見送りで閉じる", async () => {
  const body = asked(adoptionQuestion(config).trim());
  let gh = fakeGitHub({ issue: { number: 7, authorId: BOT, status: "回答待ち", assignees: ["hidakagit"], body } });
  let html = await (await openForm(7)).text();
  assert.match(html, new RegExp(config.adoption.question.replace("？", "\\？")));
  const r = await send(html, { choice: "0", next: "hidakagit-bot" });
  const [yes, no] = config.adoption.options;
  assert.equal(r.label, yes.text);
  assert.equal(comments(gh)[0], `## 回答\n**${config.adoption.question}**\n\n● **${yes.text}**\n○ ${no.text}\n${config.formOptions.map((o) => `○ ${o.text}`).join("\n")}\n\n` +
    `次のステータス: ${yes.to}\n次に動くのは: ${config.people["hidakagit-bot"].shown}`);
  assert.deepEqual([gh.issue.status, gh.issue.assignees], [yes.to, ["hidakagit-bot"]]);

  gh = fakeGitHub({ issue: { number: 7, authorId: BOT, status: "回答待ち", assignees: ["hidakagit"], body } });
  html = await (await openForm(7)).text();
  await send(html, { choice: "1" });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.done, "CLOSED"]);
  assert.equal(gh.writes.find((w) => w.stateInput).stateInput.stateReason, "NOT_PLANNED");
});

test("どの問いにも「止める」が出て、補足が無ければ断り、補足があれば保留にしてユーザーに渡し、理由は答えのコメントに残る", async () => {
  const q = "## 問い\nどうする？\n\n### 選択肢\n- A → 未着手\n- B → 未着手";
  const gh = fakeGitHub({ issue: { number: 4, authorId: ME, status: "回答待ち", assignees: ["hidakagit"], body: asked(q) } });
  const html = await (await openForm(4)).text();
  const choice = choiceOf(html, config.formOptions.find((o) => o.to === config.hold).text);
  assert.ok(choice, "止めるが選択肢に出る");
  assert.match((await send(html, { choice, next: "hidakagit" })).error, /補足が要ります/);
  assert.equal(gh.issue.status, "回答待ち");
  await send(html, { choice, next: "hidakagit", note: "来月の本番の入れ替えまで待つ" });
  assert.deepEqual([gh.issue.status, gh.issue.assignees], [config.hold, [config.ask.answerer]]);
  assert.match(comments(gh)[0], /● \*\*止める[\s\S]*補足: 来月の本番の入れ替えまで待つ/);
});

const pr = (extra) => ({ number: 3, title: "tasks#8: 題名", head: { ref: `${config.code.branchPrefix}8` }, html_url: "https://github.com/pr/3", state: "open", merged_at: null, merge_commit_sha: "M", ...extra });
const merged = (...runs) => ({ prs: [pr({ state: "closed", merged_at: "t" })], runs });
const run = (conclusion, status = "completed") => ({ name: "CI", head_sha: "M", status, conclusion, html_url: "https://github.com/run/1" });
const verifying = (code, extra) => fakeGitHub({ code, issue: { number: 8, authorId: ME, status: "検証中", assignees: ["hidakagit-bot"], ...extra } });
const codeEvent = (event, payload) => deliver(event, { repository: { full_name: config.code.repository }, ...payload });

test("Pull Request がマージされずに閉じると未着手へ戻し、マージしたら master の CI を待ち、通れば完成として閉じ、落ちれば落ちた実行を書いて未着手へ戻す", async () => {
  let gh = verifying({ prs: [pr({ state: "closed" })], runs: [] });
  await codeEvent("pull_request", { action: "closed", pull_request: { head: { ref: `${config.code.branchPrefix}8` } } });
  assert.deepEqual([gh.issue.status, gh.issue.assignees], [config.verify.back, ["hidakagit-bot"]]);
  assert.match(comments(gh)[0], /マージされずに閉じられました/);

  gh = verifying(merged(run(null, "in_progress")));
  await codeEvent("pull_request", { action: "closed", pull_request: { head: { ref: `${config.code.branchPrefix}8` } } });
  assert.deepEqual([gh.issue.status, gh.writes], ["検証中", []], "CI が終わるまでは動かさない");
  gh.code.runs = [run("success")];
  await codeEvent("workflow_run", { action: "completed", workflow_run: { head_branch: config.code.base } });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.done, "CLOSED"]);
  assert.equal(gh.writes.find((w) => w.stateInput)?.stateInput.stateReason, "COMPLETED");
  assert.equal(comments(gh)[0], "Pull Request [#3 tasks#8: 題名](https://github.com/pr/3) をマージし、そのあとの master の CI が通りました（[CI](https://github.com/run/1)）。完了にします。",
    "何をマージして何が通ったかを、開けるリンク（Markdown の形）で書く");

  gh = verifying(merged(run("success"), run("failure")));
  await codeEvent("workflow_run", { action: "completed", workflow_run: { head_branch: config.code.base } });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.verify.back, "OPEN"]);
  assert.match(comments(gh)[0], /CI が通りませんでした[\s\S]*run\/1/);
});

test("作業ブランチの Pull Request が開くと、進行中の issue は検証中になり、ユーザー確認ならユーザー、無ければ Claude の番になる", async () => {
  const open = { pull_request: { head: { ref: `${config.code.branchPrefix}8` } } };
  let gh = verifying({ prs: [pr()], runs: [] }, { status: "進行中" });
  await codeEvent("pull_request", { action: "opened", ...open });
  assert.deepEqual([gh.issue.status, gh.issue.assignees, comments(gh)], ["検証中", ["hidakagit-bot"], []]);

  gh = verifying({ prs: [pr()], runs: [] }, { status: "進行中", labels: [config.verify.label] });
  await codeEvent("pull_request", { action: "reopened", ...open });
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["検証中", [config.ask.answerer]]);

  gh = verifying({ prs: [pr()], runs: [] }, { status: "未着手" });
  await codeEvent("pull_request", { action: "opened", ...open });
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", [config.ask.answerer]]);
  assert.match(comments(gh)[0], /が開かれましたが、この issue は「未着手」なので、ステータスは動かしていません/);
});

test("作業ブランチの Pull Request が閉じたのに issue が検証中でなければ、ステータスは動かさず、理由を書き、開いていれば答える人に渡す", async () => {
  let gh = verifying(merged(), { status: "進行中" });
  await codeEvent("pull_request", { action: "closed", pull_request: { head: { ref: `${config.code.branchPrefix}8` } } });
  assert.deepEqual([gh.issue.status, gh.issue.state, gh.issue.assignees], ["進行中", "OPEN", [config.ask.answerer]]);
  assert.match(comments(gh)[0], /\[#3 tasks#8: 題名\]\(https:\/\/github\.com\/pr\/3\) がマージされましたが、この issue は「進行中」なので、ステータスは動かしていません/);

  gh = verifying({ prs: [pr({ state: "closed" })], runs: [] }, { status: "完了", state: "CLOSED" });
  await codeEvent("pull_request", { action: "closed", pull_request: { head: { ref: `${config.code.branchPrefix}8` } } });
  assert.deepEqual([gh.issue.status, gh.issue.state, gh.issue.assignees], ["完了", "CLOSED", ["hidakagit-bot"]]);
  assert.match(comments(gh)[0], /マージされずに閉じられましたが、この issue は「完了」で閉じているので/);
});

test("マージのあとの CI が通っても、本文の完了の条件にチェックの無いものが残っていれば閉じず、残りを書いて Claude に戻す", async () => {
  const gh = verifying(merged(run("success")), { body: "要約\n\n<details><summary>完了の条件</summary>\n\n- [x] 済んだこと\n- [ ] マージのあとの操作\n</details>" });
  await codeEvent("workflow_run", { action: "completed", workflow_run: { head_branch: config.code.base } });
  assert.deepEqual([gh.issue.status, gh.issue.state, gh.issue.assignees], [config.verify.back, "OPEN", ["hidakagit-bot"]]);
  assert.match(comments(gh)[0], /CI が通りました[\s\S]*閉じずに戻します[\s\S]*\n- マージのあとの操作$/);
});

test("子が閉じても、開いた子が残っていれば親は閉じない。最後の子が閉じると（人が閉じても、マージのあとゲートが閉じても）親を完了で閉じる", async () => {
  const child = { number: 8, authorId: BOT, status: "検証中", assignees: ["hidakagit-bot"] };
  const parent = { number: 20, authorId: ME, status: "保留", assignees: ["hidakagit-bot"] };
  let gh = fakeGitHub({ issue: { ...child, state: "CLOSED" }, parent: { ...parent, siblings: [{ state: "OPEN" }] } });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.issue.status, gh.parent.state, gh.parent.status], [config.done, "OPEN", "保留"]);

  gh = fakeGitHub({ issue: { ...child, state: "CLOSED" }, parent: { ...parent, siblings: [{ state: "CLOSED" }] } });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.parent.state, gh.parent.status], ["CLOSED", config.done]);
  assert.equal(gh.writes.find((w) => w.id === "I_P" && w.stateInput).stateInput.stateReason, "COMPLETED");

  gh = fakeGitHub({ issue: child, parent: { ...parent, siblings: [{ state: "CLOSED" }] }, code: merged(run("success")) });
  await codeEvent("workflow_run", { action: "completed", workflow_run: { head_branch: config.code.base } });
  assert.deepEqual([gh.issue.state, gh.parent.state, gh.parent.status], ["CLOSED", "CLOSED", config.done]);
  assert.match(comments(gh).at(-1), /子の issue が全部閉じた/);
});

test("答える人の番なら、どのステータスでも本文の先頭に回答フォームの入口へのボタンが1つ出て、Claude の番なら出ない", async () => {
  for (const status of config.statuses.filter((s) => s !== config.done))
    for (const who of Object.keys(config.people)) {
      const gh = fakeGitHub({ issue: { number: 6, authorId: ME, status, assignees: [who] } });
      await deliver("issues", { action: "assigned", issue: { node_id: "I_1" } });
      const button = `<!-- flow-gate -->\n[![対応する](https://gate.test/button.svg)](https://gate.test/answer?issue=6)\n\n**${status}**: ${config.what.question}\n<!-- /flow-gate -->\n\n`;
      assert.equal(gh.issue.body ?? "本文", `${who === config.ask.answerer ? button : ""}本文`, `${status}・${who}`);
    }
});

test("ボタンの行き先: 検証中は開いた Pull Request・実行中のマージのあとの CI へ移り、待てるものが無ければ「どうしますか？」で、完成で閉じるには補足が要る", async () => {
  const at = (code) => [verifying(code, { assignees: [config.ask.answerer] }), openForm(8)];
  for (const [code, location] of [[{ prs: [pr()], runs: [] }, "https://github.com/pr/3"], [merged(run(null, "in_progress")), "https://github.com/run/1"]]) {
    const res = await at(code)[1];
    assert.deepEqual([res.status, res.headers.get("location")], [302, location]);
  }
  const [gh, res] = at(merged());
  const html = await (await res).text();
  assert.match(html, /マージ済みですが、マージのあとの master の CI がありません/);
  const choice = choiceOf(html, config.what.options.find((o) => o.close === "COMPLETED").text);
  assert.match((await send(html, { choice })).error, /補足が要ります/);
  await send(html, { choice, note: "マージコミットを見た" });
  assert.deepEqual([gh.issue.state, gh.writes.find((w) => w.stateInput).stateInput.stateReason], ["CLOSED", "COMPLETED"]);
});

test("前提が完了で閉じていなければ進行中にできず、前提が完成でなく閉じると後ろのタスクを答える人に渡して理由を書き、ボタンの先の「どうしますか？」に前提が出る", async () => {
  const skipped = [{ number: 9, state: "CLOSED", stateReason: "NOT_PLANNED" }];
  let gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "進行中", blockedBy: skipped } });
  await move("未着手", "進行中");
  assert.deepEqual([gh.issue.status, comments(gh)[0]], ["未着手", "前提 #9 が完了（completed）で閉じていないため、「進行中」にできません。「未着手」へ戻しました。"]);

  gh = fakeGitHub({ issue: { number: 9, authorId: ME, status: "未着手", assignees: ["hidakagit-bot"], state: "CLOSED" },
    blocked: { number: 10, authorId: ME, status: "未着手", assignees: ["hidakagit-bot"], blockedBy: skipped } });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1", state_reason: "not_planned" } });
  assert.deepEqual([gh.issue.status, gh.blocked.assignees], [config.done, [config.ask.answerer]]);
  assert.match(comments(gh)[0], /前提 #9 が完了（completed）でなく閉じた/);
  assert.match(await (await openForm(10)).text(), /前提 #9 が完了（completed）で閉じていません/);
});

test("設定の不変条件: 表・入口・フォームが使う名前はすべて宣言されており、フォームは表で行けない先を出さない", () => {
  const people = Object.keys(config.people);
  for (const t of config.transitions) {
    for (const s of [...t.from, ...t.to]) assert.ok(config.statuses.includes(s), s);
    assert.ok(t.assign === null || people.includes(t.assign), t.assign);
  }
  for (const e of config.entry) assert.ok(config.statuses.includes(e.to) && people.includes(e.assign));
  for (const s of [...config.coordinator.order, config.hold, config.ask.status]) assert.ok(config.statuses.includes(s), s);
  // 採否の問い（回答待ち）と、閉じていないどのステータスの「どうしますか？」も、選択肢とフォームが足す選択肢がどれも表で行ける。
  const asks = [[parseQuestion(config, adoptionQuestion(config)), config.ask.status],
    ...config.statuses.filter((s) => s !== config.done).map((s) => [whatQuestion(config, s, ""), s])];
  for (const [q, s] of asks) assert.equal(formChoices(config, q, s).length, q.options.length + config.formOptions.length, `${s}: ${q.text}`);
});

test("行き先を書いていない選択肢（「その他」を含む）は状態を決めず、回答待ちのまま Claude の番になる（採否の問いでも）", () => {
  const q = parseQuestion(config, "## 問い\nどうする？\n\n### 選択肢\n- A → 保留\n- B\n");
  assert.equal(formChoices(config, q, config.ask.status).find((c) => c.text === "B").to, config.ask.status);
  for (const question of [q, parseQuestion(config, adoptionQuestion(config))]) {
    const stay = formChoices(config, question, config.ask.status).filter((c) => c.to === config.ask.status);
    assert.ok(stay.some((c) => c.text === config.formOptions[0].text), "「その他」は状態を決めない");
    for (const c of stay) assert.deepEqual([c.next, c.fixed], ["hidakagit-bot", true], c.text);
  }
});

test("問いの形に合わないもの（知らないステータス・選択肢が1つ）は読まない", () => {
  assert.equal(parseQuestion(config, "## 問い\nどうする？\n\n### 選択肢\n- A → 着手中\n- B\n"), null);
  assert.equal(parseQuestion(config, "## 問い\nどうする？\n\n### 選択肢\n- A\n"), null);
});

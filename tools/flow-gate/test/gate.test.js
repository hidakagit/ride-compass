// ゲートを公開の入口（index.js の fetch）で確かめる。差し替えるのは GitHub（網）だけ。
import assert from "node:assert/strict";
import { before, test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import worker from "../src/index.js";
import { adoptionQuestion, check, formChoices, parseQuestion } from "../src/rules.js";
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

test("入口: hidakagit が書いた issue は未着手で Claude に、ほかの人のものは採否待ちで hidakagit に割り当て、採否の問いのボタンを出す（コメントは書かない）", async () => {
  let gh = fakeGitHub({ issue: { number: 1, authorId: ME } });
  await deliver("projects_v2_item", item({ action: "created", sender: { login: "github-project-automation[bot]" } }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", ["hidakagit-bot"]]);
  assert.equal(gh.issue.body ?? "本文", "本文");
  assert.deepEqual(gh.issue.fields, config.project.defaults, "欄の既定値（優先度など）が入る");

  gh = fakeGitHub({ issue: { number: 2, authorId: BOT } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["採否待ち", ["hidakagit"]]);
  assert.deepEqual(comments(gh), []);
  const form = "https://gate.test/answer?issue=2";
  assert.equal(gh.issue.body, `<!-- flow-gate -->\n[![回答する](https://gate.test/button.svg)](${form})\n\n**採否待ち**: ${config.adoption.question}\n<!-- /flow-gate -->\n\n本文`);
});

test("入口: 段階（親のある issue）は、書いた人によらず未着手で Claude に割り当てる（採否は親で済んでいる）", async () => {
  const gh = fakeGitHub({ issue: { number: 3, authorId: BOT, parent: { number: 1 } } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", ["hidakagit-bot"]]);
});

test("表にある移動は通して既定の割り当てを書き、表に無い移動は戻して理由を書く", async () => {
  let gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "未着手", assignees: ["hidakagit"] } });
  await move("採否待ち", "未着手");
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", ["hidakagit-bot"]]);

  gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "進行中", assignees: ["hidakagit-bot"] } });
  await move("保留", "進行中");
  assert.equal(gh.issue.status, "保留");
  assert.match(comments(gh)[0], /「保留」から「進行中」へは動かせません.*「保留」へ戻しました/);
});

test("前提が完了で閉じていなければ進行中にできない", async () => {
  const gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "進行中", blockedBy: [{ number: 9, state: "CLOSED", stateReason: "NOT_PLANNED" }] } });
  await move("未着手", "進行中");
  assert.equal(gh.issue.status, "未着手");
  assert.match(comments(gh)[0], /前提 #9 が完了/);
});

test("ボードで完了にしたら見送りで閉じる", async () => {
  const gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "完了" } });
  await move("保留", "完了");
  assert.equal(gh.issue.state, "CLOSED");
  assert.deepEqual(gh.writes.find((w) => w.stateInput).stateInput, { value: "CLOSED", stateReason: "NOT_PLANNED" });
});


// bin/ask.js が書いたのと同じ、本文の先頭に画面に出ない形で問いを置いた本文。
const asked = (q) => `<!-- flow-gate -->\n<!-- 問い\n${q}\n-->\n<!-- /flow-gate -->\n\n本文`;
const questionId = (html) => /name="q" value="([^"]+)"/.exec(html)[1];

test("回答フォーム: 表で行ける選択肢だけを出し、答えは hidakagit の名義で問い・選択肢・判断材料ごと1つに残し、ステータスと割り当てはゲートが書き、本文の先頭の問いとボタンを消す", async () => {
  const q = "## 問い\n手順はどちらにしますか？\n\n### 選択肢\n- A 案 → 未着手\n- 私がやる → 未着手 / hidakagit\n- 進める → 進行中\n\n<details><summary>判断材料</summary>\n材料の文\n</details>";
  const gh = fakeGitHub({ issue: { number: 4, authorId: ME, status: "回答待ち", assignees: ["hidakagit"], body: asked(q) } });
  const html = await (await worker.fetch(new Request("https://gate.test/answer?issue=4"), env)).text();
  assert.match(html, /A 案/);
  assert.doesNotMatch(html, /進める/);

  const form = new FormData();
  Object.entries({ issue: "4", q: questionId(html), choice: "1", next: "hidakagit", note: "" }).forEach(([k, v]) => form.set(k, v));
  const before = gh.requests.length;
  const r = await (await worker.fetch(new Request("https://gate.test/answer", { method: "POST", body: form }), env)).json();
  assert.deepEqual(gh.requests.slice(before), ["読む", "addComment", "updateProjectV2ItemFieldValue+updateIssue"],
    "送信は、読む・答えを書く（1個）・決定を書く（ステータスと issue の更新の2個）だけ");
  assert.equal(r.label, "私がやる");
  const answer = gh.writes.find((w) => w.op === "addComment");
  assert.equal(answer.as, "hidakagit");
  assert.equal(answer.body, "## 回答\n**手順はどちらにしますか？**\n\n○ A 案\n● **私がやる**\n○ その他（コメント）\n\n" +
    "次のステータス: 未着手\n次に動くのは: hidakagit\n\n<details><summary>判断材料</summary>\n\n材料の文\n</details>");
  assert.deepEqual([gh.issue.status, gh.issue.assignees, gh.issue.body], ["未着手", ["hidakagit"], "本文"]);
});

test("問い直し: 答えて Claude の番になると回答フォームは開かず、Claude が問いを書いて hidakagit に割り当てると、本文の先頭の問いの下にボタンが出る", async () => {
  const gh = fakeGitHub({ issue: { number: 5, authorId: BOT, status: "採否待ち", assignees: ["hidakagit-bot"] } });
  const closed = await worker.fetch(new Request("https://gate.test/answer?issue=5"), env);
  assert.equal(closed.status, 404);
  assert.match(await closed.text(), /Claude の番/);

  const q = "## 問い\n新しい問い？\n\n### 選択肢\n- A → 未着手\n- B → 保留";
  Object.assign(gh.issue, { body: asked(q), assignees: ["hidakagit"] });
  await deliver("issues", { action: "assigned", issue: { node_id: "I_1" } });
  assert.equal(gh.issue.body, `<!-- flow-gate -->\n<!-- 問い\n${q}\n-->\n[![回答する](https://gate.test/button.svg)](https://gate.test/answer?issue=5)\n\n**採否待ち**: 新しい問い？\n<!-- /flow-gate -->\n\n本文`);
  assert.match(await (await worker.fetch(new Request("https://gate.test/answer?issue=5"), env)).text(), /新しい問い？/);
  await deliver("issues", { action: "labeled", issue: { node_id: "I_1" } });
  assert.equal(gh.writes.filter((w) => w.op === "updateIssue" && "body" in w).length, 1, "本文の先頭が今の状態と同じなら書き直さない");
});

test("回答フォームは置き場のラベルを全部、今の付き方のまま並べ、付け外しがそのまま効いて答えに残る（Project の欄は出さない）", async () => {
  const gh = fakeGitHub({ issue: { number: 7, authorId: BOT, status: "採否待ち", assignees: ["hidakagit"], labels: ["規模S"], fields: { [config.project.priorityField]: "中" } } });
  const html = await (await worker.fetch(new Request("https://gate.test/answer?issue=7"), env)).text();
  assert.doesNotMatch(html, /name="field:/, "Project の欄は機械が決めるので出さない");
  assert.match(html, /name="label" value="規模S" checked/);
  assert.match(html, new RegExp(`name="label" value="${config.project.urgentLabel}">`));
  const form = new FormData();
  Object.entries({ issue: "7", q: "adoption", choice: "0", next: "hidakagit-bot", note: "" }).forEach(([k, v]) => form.set(k, v));
  form.append("label", config.project.urgentLabel);
  form.append("label", config.verify.label);
  await worker.fetch(new Request("https://gate.test/answer", { method: "POST", body: form }), env);
  assert.deepEqual(gh.issue.labels.sort(), [config.project.urgentLabel, config.verify.label].sort());
  assert.match(comments(gh)[0], new RegExp(`\nラベル: \\+${config.project.urgentLabel} \\+${config.verify.label} −規模S$`));
  assert.deepEqual(gh.issue.fields, { [config.project.priorityField]: "中" }, "回答フォームは欄を変えない");
});

test("採否の問いは本文に無くても回答フォームに出て、答えると採否の問いと選択肢ごと答えに残る", async () => {
  const gh = fakeGitHub({ issue: { number: 7, authorId: BOT, status: "採否待ち", assignees: ["hidakagit"] } });
  const html = await (await worker.fetch(new Request("https://gate.test/answer?issue=7"), env)).text();
  assert.match(html, new RegExp(config.adoption.question.replace("？", "\\？")));
  const form = new FormData();
  Object.entries({ issue: "7", q: "adoption", choice: "0", next: "hidakagit-bot", note: "" }).forEach(([k, v]) => form.set(k, v));
  const r = await (await worker.fetch(new Request("https://gate.test/answer", { method: "POST", body: form }), env)).json();
  const [yes, no] = config.adoption.options;
  assert.equal(r.label, yes.text);
  assert.equal(comments(gh)[0], `## 回答\n**${config.adoption.question}**\n\n● **${yes.text}**\n○ ${no.text}\n○ ${config.formOptions[0].text}\n\n` +
    `次のステータス: ${yes.to}\n次に動くのは: ${config.people["hidakagit-bot"].shown}`);
  assert.deepEqual([gh.issue.status, gh.issue.assignees], [yes.to, ["hidakagit-bot"]]);
});

test("検証中へ動くと、ユーザーが確かめると決めたタスクはユーザーに、ほかは Claude に割り当たる", async () => {
  let gh = fakeGitHub({ issue: { number: 8, authorId: ME, status: "検証中", assignees: ["hidakagit-bot"], labels: [config.verify.label] } });
  await move("進行中", "検証中");
  assert.deepEqual(gh.issue.assignees, [config.ask.answerer]);
  gh = fakeGitHub({ issue: { number: 9, authorId: ME, status: "検証中", assignees: ["hidakagit-bot"] } });
  await move("進行中", "検証中");
  assert.deepEqual(gh.issue.assignees, ["hidakagit-bot"]);
});

const pr = (extra) => ({ number: 3, title: "tasks#8: 題名", head: { ref: `${config.code.branchPrefix}8` }, html_url: "https://github.com/pr/3", state: "open", merged_at: null, merge_commit_sha: "M", ...extra });
const run = (conclusion, status = "completed") => ({ name: "CI", head_sha: "M", status, conclusion, html_url: "https://github.com/run/1" });
const verifying = (code, extra) => fakeGitHub({ code, issue: { number: 8, authorId: ME, status: "検証中", assignees: ["hidakagit-bot"], ...extra } });
const codeEvent = (event, payload) => deliver(event, { repository: { full_name: config.code.repository }, ...payload });

test("Pull Request がマージされずに閉じると、そのタスクは未着手へ戻り、理由を読むよう書かれる", async () => {
  const gh = verifying({ prs: [pr({ state: "closed" })], runs: [] });
  await codeEvent("pull_request", { action: "closed", pull_request: { head: { ref: `${config.code.branchPrefix}8` } } });
  assert.deepEqual([gh.issue.status, gh.issue.assignees], [config.verify.back, ["hidakagit-bot"]]);
  assert.match(comments(gh)[0], /マージされずに閉じられました/);
});

test("マージしたあと master の CI を待ち、通れば完成として閉じ、落ちれば落ちた実行を書いて未着手へ戻す", async () => {
  let gh = verifying({ prs: [pr({ state: "closed", merged_at: "t" })], runs: [run(null, "in_progress")] });
  await codeEvent("pull_request", { action: "closed", pull_request: { head: { ref: `${config.code.branchPrefix}8` } } });
  assert.deepEqual([gh.issue.status, gh.writes], ["検証中", []], "CI が終わるまでは動かさない");
  gh.code.runs = [run("success")];
  await codeEvent("workflow_run", { action: "completed", workflow_run: { head_branch: config.code.base } });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.done, "CLOSED"]);
  assert.equal(gh.writes.find((w) => w.stateInput)?.stateInput.stateReason, "COMPLETED");
  assert.equal(comments(gh)[0], "Pull Request [#3 tasks#8: 題名](https://github.com/pr/3) をマージし、そのあとの master の CI が通りました（[CI](https://github.com/run/1)）。完了にします。",
    "何をマージして何が通ったかを、開けるリンク（Markdown の形）で書く");

  gh = verifying({ prs: [pr({ state: "closed", merged_at: "t" })], runs: [run("success"), run("failure")] });
  await codeEvent("workflow_run", { action: "completed", workflow_run: { head_branch: config.code.base } });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.verify.back, "OPEN"]);
  assert.match(comments(gh)[0], /CI が通りませんでした[\s\S]*run\/1/);
});

test("作業ブランチの Pull Request が閉じたのに issue が検証中でなければ、ステータスは動かさず、理由を書き、開いていれば答える人に渡す", async () => {
  let gh = verifying({ prs: [pr({ state: "closed", merged_at: "t" })], runs: [] }, { status: "進行中" });
  await codeEvent("pull_request", { action: "closed", pull_request: { head: { ref: `${config.code.branchPrefix}8` } } });
  assert.deepEqual([gh.issue.status, gh.issue.state, gh.issue.assignees], ["進行中", "OPEN", [config.ask.answerer]]);
  assert.match(comments(gh)[0], /\[#3 tasks#8: 題名\]\(https:\/\/github\.com\/pr\/3\) がマージされましたが、この issue は「進行中」なので、ステータスは動かしていません/);

  gh = verifying({ prs: [pr({ state: "closed" })], runs: [] }, { status: "完了", state: "CLOSED" });
  await codeEvent("pull_request", { action: "closed", pull_request: { head: { ref: `${config.code.branchPrefix}8` } } });
  assert.deepEqual([gh.issue.status, gh.issue.state, gh.issue.assignees], ["完了", "CLOSED", ["hidakagit-bot"]]);
  assert.match(comments(gh)[0], /マージされずに閉じられましたが、この issue は「完了」で閉じているので/);
});

test("マージのあとの CI が通っても、本文の完了の条件にチェックの無いものが残っていれば閉じず、残りを書いて Claude に戻す", async () => {
  const gh = verifying({ prs: [pr({ state: "closed", merged_at: "t" })], runs: [run("success")] },
    { body: "要約\n\n<details><summary>完了の条件</summary>\n\n- [x] 済んだこと\n- [ ] マージのあとの操作\n</details>" });
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

  gh = fakeGitHub({ issue: child, parent: { ...parent, siblings: [{ state: "CLOSED" }] },
    code: { prs: [pr({ state: "closed", merged_at: "t" })], runs: [run("success")] } });
  await codeEvent("workflow_run", { action: "completed", workflow_run: { head_branch: config.code.base } });
  assert.deepEqual([gh.issue.state, gh.parent.state, gh.parent.status], ["CLOSED", "CLOSED", config.done]);
  assert.match(comments(gh).at(-1), /子の issue が全部閉じた/);
});

test("ユーザーが確かめる番の検証中は、本文の先頭に作業ブランチの Pull Request を開くボタンが出る", async () => {
  const gh = fakeGitHub({ issue: { number: 8, authorId: ME, status: "検証中", assignees: ["hidakagit-bot"], labels: [config.verify.label] } });
  await move("進行中", "検証中");
  const q = encodeURIComponent(`is:pr head:${config.code.branchPrefix}8`);
  assert.ok(gh.issue.body.includes(`[![確かめる](https://gate.test/review.svg)](https://github.com/${config.code.repository}/pulls?q=${q})`));
});

test("設定の不変条件: 表・入口・フォームが使う名前はすべて宣言されており、フォームは表で行けない先を出さない", () => {
  const people = Object.keys(config.people);
  for (const t of config.transitions) {
    for (const s of [...t.from, ...t.to]) assert.ok(config.statuses.includes(s), s);
    assert.ok(t.assign === null || people.includes(t.assign), t.assign);
  }
  for (const e of config.entry) assert.ok(config.statuses.includes(e.to) && people.includes(e.assign));
  for (const s of [...config.coordinator.order, ...config.coordinator.busy]) assert.ok(config.statuses.includes(s), s);
  for (const [from, to] of Object.entries(config.afterAnswer)) assert.ok(check(config, from, to).ok, `${from}→${to}`);
  const adoption = parseQuestion(config, adoptionQuestion(config));
  for (const status of config.ask.statuses)
    for (const c of formChoices(config, adoption, status)) assert.ok(c.to === status || check(config, status, c.to).ok, `${status}→${c.to}`);
});

test("行き先を書いていない選択肢（「その他」を含む）で答えると、回答待ちは未着手へ進み、採否待ちは採否が決まらないまま Claude の番になる", () => {
  const q = parseQuestion(config, "## 問い\nどうする？\n\n### 選択肢\n- A → 保留\n- B\n");
  const other = (choices) => choices.find((c) => c.note);
  const answered = other(formChoices(config, q, "回答待ち"));
  assert.deepEqual([answered.to, answered.next], ["未着手", "hidakagit-bot"]);
  assert.equal(formChoices(config, q, "回答待ち").find((c) => c.text === "B").to, "未着手");
  const adoption = other(formChoices(config, parseQuestion(config, adoptionQuestion(config)), "採否待ち"));
  assert.deepEqual([adoption.to, adoption.next, adoption.fixed], ["採否待ち", "hidakagit-bot", true]);
});

test("問いの形に合わないもの（知らないステータス・選択肢が1つ）は読まない", () => {
  assert.equal(parseQuestion(config, "## 問い\nどうする？\n\n### 選択肢\n- A → 着手中\n- B\n"), null);
  assert.equal(parseQuestion(config, "## 問い\nどうする？\n\n### 選択肢\n- A\n"), null);
});

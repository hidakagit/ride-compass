// ゲートを公開の入口（index.js の fetch）で確かめる。差し替えるのは GitHub（網）だけ。
import assert from "node:assert/strict";
import { before, test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import worker from "../src/index.js";
import { adoptionQuestion, check, formChoices, parseQuestion } from "../src/rules.js";
import { fakeGitHub } from "./fake-github.js";

const env = { APP_ID: "1", WEBHOOK_SECRET: "secret", FORM_TOKEN: "form-token" };
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
  assert.deepEqual([gh.issue.labels, gh.issue.body ?? "本文"], [["状態:未着手"], "本文"]);

  gh = fakeGitHub({ issue: { number: 2, authorId: BOT } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees, gh.issue.labels], ["採否待ち", ["hidakagit"], ["状態:採否待ち"]]);
  assert.deepEqual(comments(gh), []);
  const form = "https://gate.test/answer?issue=2";
  assert.equal(gh.issue.body, `<!-- flow-gate -->\n[![回答する](https://gate.test/button.svg)](${form})\n\n**採否待ち**: ${config.adoption.question} → [回答フォーム](${form})\n<!-- /flow-gate -->\n\n本文`);
});

test("段階（親のある issue）は入口にしない", async () => {
  const gh = fakeGitHub({ issue: { number: 3, authorId: ME, parent: { number: 1 } } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual(gh.writes, []);
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

test("ボードで完了にしたら見送りで閉じ、完成で閉じて段階が残っていれば最初の段階だけ閉じて未着手に戻す", async () => {
  let gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "完了" } });
  await move("保留", "完了");
  assert.equal(gh.issue.state, "CLOSED");
  assert.deepEqual(gh.writes.find((w) => w.stateInput).stateInput, { value: "CLOSED", stateReason: "NOT_PLANNED" });

  gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "検証中", state: "CLOSED", subIssues: [{ id: "S", number: 5, state: "OPEN" }] } });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1", state_reason: "completed" } });
  assert.deepEqual(gh.writes.filter((w) => w.op === "closeIssue" || w.stateInput).map((w) => [w.issueId ?? w.id, w.stateReason ?? w.stateInput.value]), [["S", "COMPLETED"], ["I_1", "OPEN"]]);
  assert.deepEqual([gh.issue.status, gh.issue.assignees], [config.nextStage.to, [config.nextStage.assign]]);
});

test("回答フォーム: 表で行ける選択肢だけを出し、答えは hidakagit の名義、ステータスと割り当てはゲートが書き、問いを畳んで本文の先頭のリンクを消す", async () => {
  const q = "## 問い\n手順はどちらにしますか？\n\n### 選択肢\n- A 案 → 未着手\n- 私がやる → 未着手 / hidakagit\n- 進める → 進行中\n";
  const gh = fakeGitHub({ issue: { number: 4, authorId: ME, status: "回答待ち", assignees: ["hidakagit"], body: "<!-- flow-gate -->\n**回答待ち**: 手順は？ → [回答フォーム](x)\n<!-- /flow-gate -->\n\n本文", comments: [{ body: q, author: { login: "hidakagit-bot", databaseId: BOT } }] } });
  const html = await (await worker.fetch(new Request("https://gate.test/answer?issue=4"), env)).text();
  assert.match(html, /A 案/);
  assert.doesNotMatch(html, /進める/);
  assert.match(html, /今は答えられない/);

  const form = new FormData();
  Object.entries({ issue: "4", q: "C_0", choice: "1", next: "hidakagit", note: "" }).forEach(([k, v]) => form.set(k, v));
  const before = gh.requests.length, waits = [];
  const r = await (await worker.fetch(new Request("https://gate.test/answer", { method: "POST", body: form }), env, { waitUntil: (p) => waits.push(p) })).json();
  await Promise.all(waits);
  assert.deepEqual(gh.requests.slice(before), ["読む", "addComment", "updateProjectV2ItemFieldValue+updateIssue", "minimizeComment+minimizeComment"],
    "送信は、読む・答えを書く（1個）・決定を書く（ステータスと issue の更新の2個）で返し、畳むのは返したあと");
  assert.equal(waits.length, 1, "畳むのは返したあとに続ける1つだけ");
  assert.equal(r.label, "私がやる");
  const answer = gh.writes.find((w) => w.op === "addComment");
  assert.equal(answer.as, "hidakagit");
  assert.match(answer.body, /^## 回答\n問い: u#0\n選んだもの: 私がやる\n次のステータス: 未着手\n次に動くのは: hidakagit$/);
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", ["hidakagit"]]);
  assert.deepEqual(gh.writes.filter((w) => w.op === "minimizeComment").map((w) => [w.subjectId, w.as]), [["C_0", "hidakagit"], ["C_new", "hidakagit"]]);
  assert.deepEqual([gh.issue.body, gh.issue.labels], ["本文", ["状態:未着手"]]);
});

test("問い直し: 「その他」で答えた後に Claude が問いを書いて hidakagit に割り当てると、本文の先頭にリンクが出る", async () => {
  const q1 = "## 問い\n前の問い？\n\n### 選択肢\n- A → 未着手\n- B → 保留\n";
  const q2 = "## 問い\n新しい問い？\n\n### 選択肢\n- A → 未着手\n- B → 保留\n";
  const gh = fakeGitHub({ issue: { number: 5, authorId: ME, status: "回答待ち", assignees: ["hidakagit"], comments: [
    { body: q1, author: { login: "hidakagit-bot", databaseId: BOT } },
    { body: "## 回答\n問い: u#0\n選んだもの: その他（コメント）\n次のステータス: 回答待ち", author: { login: "hidakagit" } },
    { body: q2, author: { login: "hidakagit-bot", databaseId: BOT } },
  ] } });
  await deliver("issues", { action: "assigned", issue: { node_id: "I_1" } });
  assert.ok(gh.issue.body.startsWith("<!-- flow-gate -->\n[![回答する]"));
  assert.match(gh.issue.body, /\*\*回答待ち\*\*: 新しい問い？ → \[回答フォーム\]\(https:\/\/gate\.test\/answer\?issue=5\)/);
  await deliver("issues", { action: "labeled", issue: { node_id: "I_1" } });
  assert.equal(gh.writes.filter((w) => w.op === "updateIssue" && "body" in w).length, 1, "リンクが今の状態と同じなら書き直さない");
});

test("採否の問いはコメントが無くても回答フォームに出て、答えると採否の問いへの答えとして記録される", async () => {
  const gh = fakeGitHub({ issue: { number: 7, authorId: BOT, status: "採否待ち", assignees: ["hidakagit"] } });
  const html = await (await worker.fetch(new Request("https://gate.test/answer?issue=7"), env)).text();
  assert.match(html, new RegExp(config.adoption.question.replace("？", "\\？")));
  const form = new FormData();
  Object.entries({ issue: "7", q: "adoption", choice: "0", next: "hidakagit-bot", note: "" }).forEach(([k, v]) => form.set(k, v));
  const waits = [];
  const r = await (await worker.fetch(new Request("https://gate.test/answer", { method: "POST", body: form }), env, { waitUntil: (p) => waits.push(p) })).json();
  await Promise.all(waits);
  assert.equal(r.label, config.adoption.options[0].text);
  assert.match(comments(gh)[0], /^## 回答\n問い: https:\/\/github\.com\/[^\n]+\/issues\/7#採否\n/);
  assert.deepEqual([gh.issue.status, gh.issue.assignees], [config.adoption.options[0].to, ["hidakagit-bot"]]);
  assert.deepEqual(gh.writes.filter((w) => w.op === "minimizeComment").map((w) => w.subjectId), ["C_new"], "採否の問いにはコメントが無いので、畳むのは答えだけ");
});

test("ステータスのラベルは Project の Status と同じ1つだけにそろい、手で付け替えても戻る", async () => {
  const gh = fakeGitHub({ issue: { number: 6, authorId: ME, status: "未着手", labels: ["規模S", "状態:完了", "状態:保留"] } });
  await deliver("issues", { action: "labeled", issue: { node_id: "I_1" } });
  assert.deepEqual(gh.issue.labels.sort(), ["状態:未着手", "規模S"].sort());
});

test("設定の不変条件: 表・入口・フォームが使う名前はすべて宣言されており、フォームは表で行けない先を出さない", () => {
  const people = Object.keys(config.people);
  for (const t of config.transitions) {
    for (const s of [...t.from, ...t.to]) assert.ok(config.statuses.includes(s), s);
    assert.ok(t.assign === null || people.includes(t.assign), t.assign);
  }
  for (const e of config.entry) assert.ok(config.statuses.includes(e.to) && people.includes(e.assign));
  const adoption = parseQuestion(config, adoptionQuestion(config));
  for (const status of config.ask.statuses)
    for (const c of formChoices(config, adoption, status)) assert.ok(c.to === status || check(config, status, c.to).ok, `${status}→${c.to}`);
});

test("問いの形に合わないもの（知らないステータス・選択肢が1つ）は読まない", () => {
  assert.equal(parseQuestion(config, "## 問い\nどうする？\n\n### 選択肢\n- A → 着手中\n- B\n"), null);
  assert.equal(parseQuestion(config, "## 問い\nどうする？\n\n### 選択肢\n- A\n"), null);
});

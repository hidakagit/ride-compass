// 約束 1〜11（ゲート・回答フォーム・問いの形）を、公開の入口（index.js の fetch）で確かめる。差し替えるのは GitHub（網）だけ。
// 確かめるのは約束の結果（ステータス・担当者・開き閉じ・本文・書いたかどうか）で、文言は確かめない。
import assert from "node:assert/strict";
import { before, test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import worker from "../src/index.js";
import { Gate } from "../src/gate.js";
import { parseQuestion } from "../src/rules.js";
import { fakeGitHub } from "./fake-github.js";

const env = { APP_ID: "1", WEBHOOK_SECRET: "secret", FORM_TOKEN: "form-token" };
before(async () => {
  const { privateKey } = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign"]);
  env.APP_KEY = Buffer.from(await crypto.subtle.exportKey("pkcs8", privateKey)).toString("base64");
});

async function deliver(event, payload) {
  const body = JSON.stringify({ sender: { login: config.user }, ...payload });
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.WEBHOOK_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = Buffer.from(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body))).toString("hex");
  const waits = [];
  await worker.fetch(new Request("https://gate.test/webhook", { method: "POST", body, headers: { "x-github-event": event, "x-hub-signature-256": `sha256=${sig}` } }), env, { waitUntil: (p) => waits.push(p) });
  await Promise.all(waits);
}
const item = (extra) => ({ projects_v2_item: { content_type: "Issue", project_node_id: "PVT", content_node_id: "I_1" }, ...extra });
const move = (from, to) => deliver("projects_v2_item", item({ action: "edited", changes: { field_value: { field_name: config.project.statusField, from: { name: from }, to: { name: to } } } }));
const said = (gh) => gh.writes.filter((w) => w.op === "addComment").map((w) => w.body);
const left = "<details><summary>完了の条件</summary>\n\n- [x] 済んだこと\n- [ ] マージのあとの操作\n</details>";
const formLink = (n) => `${config.urls.form}/answer?issue=${n}`;

test("1 遷移は表だけで照らし、表に無い移動は前へ戻して理由をコメントする", async () => {
  let gh = fakeGitHub({ issue: { number: 1, status: "保留" } });
  await move("未着手", "保留");
  assert.deepEqual([gh.issue.status, said(gh).length], ["保留", 0]);
  gh = fakeGitHub({ issue: { number: 1, status: "進行中" } });
  await move("保留", "進行中");
  assert.deepEqual([gh.issue.status, said(gh).length], ["保留", 1]);
});

test("2 完成で完了に入るのは、どの経路でも完了の条件が残っていないときだけ。見送りは問わない。完了からは戻せない", async () => {
  for (const [path, act] of [["閉じる操作", () => deliver("issues", { action: "closed", issue: { node_id: "I_1" } })], ["ボード", () => move("未着手", config.done)]]) {
    const gh = fakeGitHub({ issue: { number: 8, status: path === "ボード" ? config.done : "未着手", state: path === "ボード" ? "OPEN" : "CLOSED", lastClose: [{ stateReason: "COMPLETED" }], body: left } });
    await act();
    assert.deepEqual([gh.issue.status, gh.issue.state, said(gh).length], ["未着手", "OPEN", 1], path);
  }
  let gh = fakeGitHub({ issue: { number: 8, status: "未着手", state: "CLOSED", lastClose: [{ stateReason: "NOT_PLANNED" }], body: left } });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.done, "CLOSED"], "見送り");
  gh = fakeGitHub({ issue: { number: 8, status: config.done, lastClose: [{ stateReason: "COMPLETED" }] } });
  await deliver("issues", { action: "reopened", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.done, "CLOSED"], "開き直しは閉じ直す");
});

test("3 担当者はステータスの番で、手で変えても戻る", async () => {
  for (const [status, owner] of [["未着手", config.claude], ["回答待ち", config.user]]) {
    const gh = fakeGitHub({ issue: { number: 1, status, assignees: [config.user, config.claude] } });
    await deliver("issues", { action: "assigned", issue: { node_id: "I_1" } });
    assert.deepEqual(gh.issue.assignees, [owner], status);
  }
});

test("4 入口: ユーザーの起票と段階は未着手、Claude の起票は回答待ちで採否の問いをコメントに置く。優先度が空なら既定、段階は親の値", async () => {
  const priority = config.project.priorityField;
  let gh = fakeGitHub({ issue: { number: 1, status: "進行中" } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.fields[priority]], ["未着手", config.project.defaults[priority]]);
  gh = fakeGitHub({ issue: { number: 3, author: config.claude }, parent: { number: 1, fields: { [priority]: "高" } } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.fields[priority]], ["未着手", "高"]);
  gh = fakeGitHub({ issue: { number: 2, author: config.claude, fields: { [priority]: "低" } } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.fields[priority], said(gh).length, Boolean(parseQuestion(said(gh)[0]))], ["回答待ち", "低", 1, true]);
});

test("5 本文の先頭には、回答待ちの間だけ回答フォームへのボタンが1つある", async () => {
  const gh = fakeGitHub({ issue: { number: 2, author: config.claude } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.equal(gh.issue.body.split(formLink(2)).length, 2);
  await move("回答待ち", "保留");
  assert.equal(gh.issue.body.includes(formLink(2)), false);
});

const pr = (action, extra) => deliver("pull_request", { repository: { full_name: config.code.repository }, action, pull_request: { number: 3, title: "題名", head: { ref: `${config.code.branchPrefix}8` }, html_url: "u", merged: false, ...extra } });
test("6 Pull Request: 開くと進行中は検証中へ。閉じたら検証中だけを、マージされずなら未着手、マージされたら残りが無ければ完了・あれば未着手へ", async () => {
  let gh = fakeGitHub({ issue: { number: 8, status: "進行中" } });
  await pr("opened");
  assert.equal(gh.issue.status, "検証中");
  for (const [status, extra, body, want] of [["検証中", {}, "本文", "未着手"], ["検証中", { merged: true }, "本文", config.done], ["検証中", { merged: true }, left, "未着手"], ["回答待ち", { merged: true }, "本文", "回答待ち"]]) {
    gh = fakeGitHub({ issue: { number: 8, status, body } });
    await pr("closed", extra);
    assert.equal(gh.issue.status, want, `${status} ${JSON.stringify(extra)}`);
  }
});

test("7 公開の直後の揃え: 開いた issue を今の規則の姿へ揃え、揃っていれば書かない", async () => {
  const gh = fakeGitHub({ issue: { number: 3, status: "回答待ち", assignees: [config.claude] } });
  const gate = await Gate.open({ GITHUB_TOKEN: "bot-token" }, config);
  assert.deepEqual(await gate.refreshAll(), [3]);
  assert.deepEqual([gh.issue.assignees, gh.issue.body.includes(formLink(3))], [[config.user], true]);
  assert.deepEqual(await gate.refreshAll(), []);
});

// 回答フォームで答える（問いは Claude のコメント）。次のステータスは画面に出た選択肢の文字で選ぶ。
const waiting = (body = "本文") => fakeGitHub({ issue: { number: 4, status: config.waiting, assignees: [config.user], body, comments: [{ author: config.claude, body: "## 問い\nどうする？" }] } });
async function answer(next, done = []) {
  const html = await (await worker.fetch(new Request("https://gate.test/answer?issue=4"), env)).text();
  const choices = [...html.matchAll(/name="next" value="(\d+)" data-text="([^"]*)"( data-complete="1")?/g)];
  const pick = next === "完成" ? choices.find((m) => m[3]) : choices[next];
  const form = new FormData();
  Object.entries({ issue: "4", q: /name="q" value="([^"]+)"/.exec(html)[1], next: pick[1] }).forEach(([k, v]) => form.set(k, v));
  done.forEach((d) => form.append("done", d));
  await worker.fetch(new Request("https://gate.test/answer", { method: "POST", body: form }), env);
  return choices.length;
}

test("9 回答フォームで選んだ次のステータスへ動く（表で回答待ちから行ける先。完了は完成と見送り）", async () => {
  const want = config.transitions[config.waiting].flatMap((to) => (to === config.done ? [`${to}:COMPLETED`, `${to}:NOT_PLANNED`] : [to]));
  const reached = [];
  for (let i = 0; i < want.length; i++) {
    const gh = waiting();
    assert.equal(await answer(i), want.length);
    reached.push(gh.issue.state === "CLOSED" ? `${gh.issue.status}:${gh.writes.find((w) => w.stateInput).stateInput.stateReason}` : gh.issue.status);
  }
  assert.deepEqual(reached, want);
});

test("9 回答フォームの完成は、残りの完了の条件を全部チェックしたときだけ通り、チェックは本文に付く。通らなければ何も書かない", async () => {
  let gh = waiting(left);
  await answer("完成");
  assert.deepEqual([gh.issue.status, gh.writes.length], [config.waiting, 0]);
  gh = waiting(left);
  await answer("完成", ["マージのあとの操作"]);
  assert.deepEqual([gh.issue.status, gh.issue.state, /- \[x\] マージのあとの操作/.test(gh.issue.body)], [config.done, "CLOSED", true]);
});

test("11 問いは「## 問い」・問いの文・「### 案」と1行1案・判断材料だけで、ほかの行があれば形に合わない", () => {
  assert.deepEqual(parseQuestion("## 問い\nどうする？\n\n### 案\n- A\n- B\n\n<details><summary>判断材料</summary>\n### 見出し\n</details>"), { text: "どうする？", plans: ["A", "B"], material: "### 見出し" });
  for (const bad of ["## 問い\n\n### 案\n- A", "## 問い\nどうする？\n補足の行", "## 問い\nどうする？\n\n### 案\n", "## 問い\nどうする？\n\n### 案\n- A\nB"]) assert.equal(parseQuestion(bad), null, bad);
});

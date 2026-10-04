// ゲートと回答フォームを公開の入口（index.js の fetch）で確かめる。差し替えるのは GitHub（網）だけ。
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

async function deliver(event, payload, secret = env.WEBHOOK_SECRET) {
  const body = JSON.stringify({ sender: { login: config.user }, ...payload });
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = Buffer.from(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body))).toString("hex");
  const waits = [];
  const res = await worker.fetch(new Request("https://gate.test/webhook", { method: "POST", body, headers: { "x-github-event": event, "x-hub-signature-256": `sha256=${sig}` } }), env, { waitUntil: (p) => waits.push(p) });
  await Promise.all(waits);
  return res;
}
const item = (extra) => ({ projects_v2_item: { content_type: "Issue", project_node_id: "PVT", content_node_id: "I_1" }, ...extra });
const move = (from, to) => deliver("projects_v2_item", item({ action: "edited", changes: { field_value: { field_name: config.project.statusField, from: { name: from }, to: { name: to } } } }));
const said = (gh) => gh.writes.filter((w) => w.op === "addComment").map((w) => w.body);
const left = "<details><summary>完了の条件</summary>\n\n- [x] 済んだこと\n- [ ] マージのあとの操作\n</details>";
const button = (n) => `<!-- flow-gate -->\n[![回答する](${config.urls.gate}/button.svg)](${config.urls.form}/answer?issue=${n})\n<!-- /flow-gate -->\n\n`;

test("署名が合わない出来事は受けず、ゲート自身が起こした出来事は捨てる", async () => {
  const gh = fakeGitHub({ issue: { number: 1 } });
  assert.equal((await deliver("projects_v2_item", item({ action: "created" }), "wrong")).status, 401);
  await deliver("projects_v2_item", item({ action: "created", sender: { login: config.gate } }));
  assert.deepEqual(gh.writes, []);
});

test("遷移は表だけで照らし、表に無い移動は前へ戻して理由を書く", async () => {
  let gh = fakeGitHub({ issue: { number: 1, status: "保留" } });
  await move("未着手", "保留");
  assert.deepEqual([gh.issue.status, said(gh)], ["保留", []]);
  gh = fakeGitHub({ issue: { number: 1, status: "進行中" } });
  await move("保留", "進行中");
  assert.equal(gh.issue.status, "保留");
  assert.match(said(gh)[0], /「保留」から「進行中」へは動かせません（遷移の表に無い）。「保留」へ戻しました/);
});

test("完成で完了に入るのは、どの経路でも完了の条件が残っていないときだけ。見送りは問わない。完了からは戻せない", async () => {
  for (const [path, act] of [["閉じる操作", () => deliver("issues", { action: "closed", issue: { node_id: "I_1" } })], ["ボード", () => move("未着手", config.done)]]) {
    const gh = fakeGitHub({ issue: { number: 8, status: path === "ボード" ? config.done : "未着手", state: path === "ボード" ? "OPEN" : "CLOSED", lastClose: [{ stateReason: "COMPLETED" }], body: left } });
    await act();
    assert.deepEqual([gh.issue.status, gh.issue.state], ["未着手", "OPEN"], path);
    assert.match(said(gh)[0], /完成にするには次が残っています。[\s\S]*「未着手」へ戻しました。$/, path);
  }
  let gh = fakeGitHub({ issue: { number: 8, status: "未着手", state: "CLOSED", lastClose: [{ stateReason: "NOT_PLANNED" }], body: left } });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.done, "CLOSED"], "見送り");
  gh = fakeGitHub({ issue: { number: 8, status: config.done, lastClose: [{ stateReason: "COMPLETED" }] } });
  await deliver("issues", { action: "reopened", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.done, "CLOSED"], "開き直しは閉じ直す");
});

test("担当者はステータスの番で、手で変えても戻る", async () => {
  const gh = fakeGitHub({ issue: { number: 1, status: "未着手", assignees: [config.user] } });
  await deliver("issues", { action: "assigned", issue: { node_id: "I_1" } });
  assert.deepEqual(gh.issue.assignees, [config.claude]);
});

test("入口: ユーザーの起票と段階は未着手、Claude の起票は回答待ちで採否の問いをコメントに置き、本文の先頭にボタン。優先度は既定か親の値", async () => {
  let gh = fakeGitHub({ issue: { number: 1, status: "進行中" } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees, gh.issue.fields[config.project.priorityField], gh.issue.body], ["未着手", [config.claude], "中", "本文"]);
  gh = fakeGitHub({ issue: { number: 3, author: config.claude }, parent: { number: 1, fields: { [config.project.priorityField]: "高" } } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.fields[config.project.priorityField]], ["未着手", "高"]);
  gh = fakeGitHub({ issue: { number: 2, author: config.claude } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees, said(gh), gh.issue.body], ["回答待ち", [config.user], [`## 問い\n${config.adoption}`], `${button(2)}本文`]);
  await move("回答待ち", "保留");
  assert.equal(gh.issue.body, "本文", "回答待ちを出るとボタンは消える");
  gh = fakeGitHub({ issue: { number: 2, status: "回答待ち", assignees: [config.user], body: `${button(2)}本文`.replaceAll("\n", "\r\r\n") } });
  await deliver("issues", { action: "edited", issue: { node_id: "I_1" } });
  assert.equal(gh.issue.body.match(/回答する/g).length, 1, "改行が壊れて届いた本文でもボタンは1つ");
});

const pr = (action, extra) => deliver("pull_request", { repository: { full_name: config.code.repository }, action, pull_request: { number: 3, title: "題名", head: { ref: `${config.code.branchPrefix}8` }, html_url: "u", merged: false, ...extra } });
test("Pull Request: 開くと進行中は検証中へ。閉じたら検証中だけを、マージされずなら未着手、マージされたら残りが無ければ完了・あれば未着手へ", async () => {
  const task = (status, body) => fakeGitHub({ issue: { number: 8, status, body } });
  let gh = task("進行中");
  await pr("opened");
  assert.equal(gh.issue.status, "検証中");
  for (const [status, extra, body, want] of [["検証中", {}, "本文", "未着手"], ["検証中", { merged: true }, "本文", config.done], ["検証中", { merged: true }, left, "未着手"], ["回答待ち", { merged: true }, "本文", "回答待ち"]]) {
    gh = task(status, body);
    await pr("closed", extra);
    assert.equal(gh.issue.status, want, `${status} ${JSON.stringify(extra)}`);
  }
});

test("公開の直後の揃え: 開いた issue を今の規則の姿へ揃え、揃っていれば書かない", async () => {
  const gh = fakeGitHub({ issue: { number: 3, status: "回答待ち", assignees: [config.claude] } });
  const gate = await Gate.open({ GITHUB_TOKEN: "bot-token" }, config);
  assert.deepEqual(await gate.refreshAll(), [3]);
  assert.deepEqual([gh.issue.assignees, gh.issue.body], [[config.user], `${button(3)}本文`]);
  assert.deepEqual(await gate.refreshAll(), []);
});

// 回答待ちのタスク。問いは Claude のコメントにあり、その後ろに担当の報告が続いてよい。
const waiting = (q, extra = {}, github = {}) => fakeGitHub({ ...github, issue: { number: 4, status: "回答待ち", assignees: [config.user], body: `${button(4)}本文`,
  comments: [{ author: config.claude, body: q }, { author: config.claude, body: "担当の報告" }], ...extra } });
const open = async () => (await worker.fetch(new Request("https://gate.test/answer?issue=4"), env)).text();
const nexts = (html) => [...html.matchAll(/name="next" value="\d+" required data-text="([^"]*)"/g)].map((m) => m[1]);
async function answer(html, { next, plan, note = "", labels = [], done = [] }) {
  const form = new FormData();
  Object.entries({ issue: "4", q: /name="q" value="([^"]+)"/.exec(html)[1], next: String(nexts(html).indexOf(next)), note }).forEach(([k, v]) => form.set(k, v));
  if (plan) form.set("plan", plan);
  labels.forEach((l) => form.append("label", l));
  done.forEach((d) => form.append("done", d));
  return (await worker.fetch(new Request("https://gate.test/answer", { method: "POST", body: form }), env)).json();
}

test("回答フォームは回答待ちのときだけ開き、最新の問いのコメントを読み、開いたあとに新しい問いが来たら送信を断る", async () => {
  fakeGitHub({ issue: { number: 4, status: "保留" } });
  const closed = await worker.fetch(new Request("https://gate.test/answer?issue=4"), env);
  assert.deepEqual([closed.status, /いまは回答待ちではありません/.test(await closed.text())], [404, true]);
  const gh = waiting("## 問い\n前の問い？");
  const old = await open();
  gh.issue.comments.push({ author: config.claude, body: "## 問い\n新しい問い？" });
  assert.match(await open(), /<p>新しい問い？<\/p>/);
  assert.match((await answer(old, { next: "未着手" })).error, /問いが新しくなっています/);
});

test("並びは問い・判断材料・本文と最近のコメント・回答・次のステータス（表の行き先。最初が既定）・ラベル。判断材料が描けなければ文字のまま", async () => {
  waiting("## 問い\n重い CI を飛ばしますか\n\n### 案\n- 飛ばす\n- 飛ばさない\n\n<details><summary>判断材料</summary>\n材料の文\n</details>");
  const html = await open();
  const at = (re) => html.search(re);
  assert.ok([/重い CI/, /<details open><summary>判断材料/, /<summary>本文/, /<summary>最近のコメント/, /name="plan"/, /name="next"/, /<summary>ラベル/].map(at).every((v, i, a) => v > 0 && (!i || a[i - 1] < v)), "並び");
  assert.deepEqual(nexts(html), ["未着手", "保留", "完了（完成）", "完了（見送り）"]);
  assert.match(html, /data-text="未着手" checked>/);
  waiting("## 問い\nどうする？\n\n<details><summary>判断材料</summary>\n<b>タグ</b>\n</details>", {}, { markdown: false });
  assert.match(await open(), /white-space:pre-wrap">&#60;b&#62;タグ/);
});

test("答えは1つのコメント（ユーザーの名義）に残り、行き先ごとに動く。完成は残りの条件を全部確かめたときだけ通り、本文にもチェックが付く", async () => {
  for (const [next, status, reason] of [["未着手", "未着手"], ["保留", "保留"], ["完了（見送り）", config.done, "NOT_PLANNED"]]) {
    const gh = waiting("## 問い\nどうする？\n\n### 案\n- A\n- B", { labels: ["規模S"] });
    await answer(await open(), { next, plan: "A", note: "補足", labels: [config.project.urgentLabel] });
    assert.equal(gh.issue.status, status, next);
    if (reason) assert.equal(gh.writes.find((w) => w.stateInput).stateInput.stateReason, reason);
    assert.deepEqual([gh.writes.find((w) => w.op === "addComment").as, said(gh)[0]], [config.user, `## 回答\n**どうする？**\n\n回答: A\n次のステータス: ${next}\nラベル: +${config.project.urgentLabel} −規模S\n補足: 補足`]);
  }
  const gh = waiting("## 問い\nどうする？", { body: `${button(4)}${left}` });
  const html = await open();
  assert.match((await answer(html, { next: "完了（完成）" })).error, /完成にするには次が残っています/);
  assert.deepEqual([gh.issue.status, said(gh)], ["回答待ち", []], "断った答えは記録も書かない");
  await answer(html, { next: "完了（完成）", done: ["マージのあとの操作"] });
  assert.deepEqual([gh.issue.status, gh.issue.state, /- \[x\] マージのあとの操作/.test(gh.issue.body)], [config.done, "CLOSED", true]);
});

test("問いは「## 問い」・問いの文・「### 案」と1行1案・判断材料だけで、ほかの行があれば形に合わない", () => {
  assert.deepEqual(parseQuestion("## 問い\nどうする？\n\n### 案\n- A\n- B\n\n<details><summary>判断材料</summary>\n### 見出し\n</details>"), { text: "どうする？", plans: ["A", "B"], material: "### 見出し" });
  for (const bad of ["## 問い\n\n### 案\n- A", "## 問い\nどうする？\n補足の行", "## 問い\nどうする？\n\n### 案\n", "## 問い\nどうする？\n\n### 案\n- A\nB"]) assert.equal(parseQuestion(bad), null, bad);
});

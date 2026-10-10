// 約束 1〜12（ゲート・回答フォーム・問いの形）を、ゲートの入口（gate.js: handleEvent）と回答フォームの入口（form.js: answerForm）で
// 確かめる。設定は架空のもの（fake-github.js: config）を渡し、差し替えるのは GitHub（網）だけ。確かめるのは約束の結果（ステータス・
// 担当者・開き閉じ・本文・書いたかどうか）。
// ここで見ないもの: 文言・画面の並びと見た目（合意したモックと実物で見比べる）・出来事の署名（GitHub が受け手に求める標準の手順で、
// 約束ではない）・道具（bin）の起動（静的な誤りは CI の静的な検査が持つ）。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { before, test } from "node:test";
import { answerForm } from "../src/form.js";
import { handleEvent } from "../src/gate.js";
import { checkQuestion, parseQuestion } from "../src/rules.js";
import { config, fakeGitHub } from "./fake-github.js";

const env = { APP_ID: "1", FORM_TOKEN: "form-token" };
before(async () => {
  const { privateKey } = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign"]);
  env.APP_KEY = Buffer.from(await crypto.subtle.exportKey("pkcs8", privateKey)).toString("base64");
});

const deliver = (event, payload) => handleEvent(env, config, event, { sender: { login: config.user }, ...payload });
const item = (extra) => ({ projects_v2_item: { content_type: "Issue", project_node_id: "PVT", content_node_id: "I_1" }, ...extra });
const move = (from, to) => deliver("projects_v2_item", item({ action: "edited", changes: { field_value: { field_name: config.project.statusField, from: { name: from }, to: { name: to } } } }));
const said = (gh) => gh.writes.filter((w) => w.op === "addComment").map((w) => w.body);
const left = "<details><summary>完了の条件</summary>\n\n- [x] 済んだこと\n- [ ] マージのあとの操作\n</details>";

test("1 遷移は表だけで照らし、表に無い移動は前へ戻して理由をコメントする", async () => {
  let gh = fakeGitHub({ issue: { number: 1, status: "置き" } });
  await move("前", "置き");
  assert.deepEqual([gh.issue.status, said(gh).length], ["置き", 0]);
  gh = fakeGitHub({ issue: { number: 1, status: "中" } });
  await move("置き", "中");
  assert.deepEqual([gh.issue.status, said(gh).length], ["置き", 1]);
});

test("2 完成で完了に入るのは、どの経路でも完了の条件が残っていないときだけ。見送りは問わない。完了からは戻せない", async () => {
  for (const [path, act] of [["閉じる操作", () => deliver("issues", { action: "closed", issue: { node_id: "I_1" } })], ["ボード", () => move("前", "済")]]) {
    const gh = fakeGitHub({ issue: { number: 8, status: path === "ボード" ? "済" : "前", state: path === "ボード" ? "OPEN" : "CLOSED", lastClose: [{ stateReason: "COMPLETED" }], body: left } });
    await act();
    assert.deepEqual([gh.issue.status, gh.issue.state, said(gh).length], ["前", "OPEN", 1], path);
  }
  let gh = fakeGitHub({ issue: { number: 8, status: "前", state: "CLOSED", lastClose: [{ stateReason: "NOT_PLANNED" }], body: left } });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.issue.status, gh.issue.state], ["済", "CLOSED"], "見送り");
  gh = fakeGitHub({ issue: { number: 8, status: "済", lastClose: [{ stateReason: "COMPLETED" }] } });
  await deliver("issues", { action: "reopened", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.issue.status, gh.issue.state], ["済", "CLOSED"], "開き直しは閉じ直す");
});

test("3 担当者はステータスの番で、手で変えても戻る", async () => {
  for (const [status, owner] of [["前", "c"], ["答え待ち", "u"]]) {
    const gh = fakeGitHub({ issue: { number: 1, status, assignees: ["u", "c"] } });
    await deliver("issues", { action: "assigned", issue: { node_id: "I_1" } });
    assert.deepEqual(gh.issue.assignees, [owner], status);
  }
});

test("4 入口: 起こしたことが判断なので未着手で、Claude が起こした親の無い要望だけは保留で入り、どれにも問いを置かない。段階は優先度の欄が空なら親の値を継ぎ、ほかの欄は書かない", async () => {
  for (const issue of [{}, { author: "c", type: "保" }, { author: "c", type: "要" }, { type: "要" }]) {
    const gh = fakeGitHub({ issue: { number: 2, status: "中", ...issue } });
    await deliver("projects_v2_item", item({ action: "created" }));
    assert.deepEqual([gh.issue.status, said(gh).length, gh.issue.fields.重さ], [issue.author === "c" && issue.type === "要" ? "置き" : "前", 0, undefined], JSON.stringify(issue));
  }
  let gh = fakeGitHub({ issue: { number: 3, author: "c", type: "要" }, parent: { number: 1, fields: { 重さ: "上" } } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.fields.重さ], ["前", "上"]);
  gh = fakeGitHub({ issue: { number: 3, author: "c", fields: { 重さ: "下" } }, parent: { number: 1, fields: { 重さ: "上" } } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.fields.重さ], ["前", "下"]);
});

// 形（fake-github.js: config.questionTemplate）に合う問い。
const Q = "## 問い\nどうする？\n\n### 案\n- A\n- B\n\n<details><summary>判断材料</summary>\n\n**約束**: 約束\n**案ごと**: A なら…\n**推奨**: A\n</details>";
test("5 本文の先頭には、回答待ちの間だけ回答フォームへのボタンがある", async () => {
  const gh = fakeGitHub({ issue: { number: 2, status: "答え待ち", comments: [{ author: "c", body: Q }] } });
  await move("置き", "答え待ち");
  assert.notEqual(gh.issue.body, "本文");
  await move("答え待ち", "置き");
  assert.equal(gh.issue.body, "本文");
});

const pr = (action, extra) => deliver("pull_request", { repository: { full_name: config.code.repository }, action, pull_request: { number: 3, title: "題名", head: { ref: `${config.code.branchPrefix}8` }, html_url: "u", merged: false, ...extra } });
test("6 Pull Request: 開くと進行中は検証中へ。閉じたら検証中だけを、マージされずなら未着手、マージされたら残りが無ければ完了・あれば未着手へ", async () => {
  let gh = fakeGitHub({ issue: { number: 8, status: "中" } });
  await pr("opened");
  assert.equal(gh.issue.status, "検");
  for (const [status, extra, body, want] of [["検", {}, "本文", "前"], ["検", { merged: true }, "本文", "済"], ["検", { merged: true }, left, "前"], ["答え待ち", { merged: true }, "本文", "答え待ち"]]) {
    gh = fakeGitHub({ issue: { number: 8, status, body } });
    await pr("closed", extra);
    assert.equal(gh.issue.status, want, `${status} ${JSON.stringify(extra)}`);
  }
});

// 回答フォームで答える（問いは Claude のコメント）。次のステータスは、画面に出た選択肢の何番目か、完成なら完成の印の付いたもので選ぶ。
const waiting = (body = "本文") => fakeGitHub({ issue: { number: 4, status: "答え待ち", assignees: ["u"], body, comments: [{ author: "c", body: "## 問い\nどうする？" }] } });
async function answer(next, done = []) {
  const html = await (await answerForm(new Request("https://form.example/answer?issue=4"), env, config)).text();
  const choices = [...html.matchAll(/<input [^>]*name="next"[^>]*>/g)].map(([tag]) => ({ value: /value="(\d+)"/.exec(tag)[1], complete: tag.includes("data-complete") }));
  const form = new FormData();
  Object.entries({ issue: "4", q: /name="q" value="([^"]+)"/.exec(html)[1], next: (next === "完成" ? choices.find((c) => c.complete) : choices[next]).value }).forEach(([k, v]) => form.set(k, v));
  done.forEach((d) => form.append("done", d));
  await answerForm(new Request("https://form.example/answer", { method: "POST", body: form }), env, config);
  return choices.length;
}

test("9 回答フォームで選んだ次のステータスへ動く（表で回答待ちから行ける先。完了は完成と見送り）", async () => {
  const reached = new Set();
  for (let i = 0, n = 1; i < n; i++) {
    const gh = waiting();
    n = await answer(i);
    reached.add(gh.issue.state === "CLOSED" ? `${gh.issue.status}:${gh.writes.find((w) => w.stateInput).stateInput.stateReason}` : gh.issue.status);
  }
  assert.deepEqual(reached, new Set(["前", "置き", "済:COMPLETED", "済:NOT_PLANNED"]));
});

test("9 回答フォームの完成は、残りの完了の条件を全部チェックしたときだけ通り、チェックは本文に付く。通らなければ何も書かない", async () => {
  let gh = waiting(left);
  await answer("完成");
  assert.deepEqual([gh.issue.status, gh.writes.length], ["答え待ち", 0]);
  gh = waiting(left);
  await answer("完成", ["マージのあとの操作"]);
  assert.deepEqual([gh.issue.status, gh.issue.state, /- \[x\] マージのあとの操作/.test(gh.issue.body)], ["済", "CLOSED", true]);
});

test("12 回答待ちへは、最新の問いか答えが形に合う答えていない問いのときだけ入る。合わなければ前へ戻して理由を書き、ゲートは問いを置かない", async () => {
  const q = { author: "c", body: Q };
  const a = { author: "u", body: "## 回答\n**どうする？**\n\n次のステータス: 置き" };
  for (const [comments, want] of [[[q], 0], [[a, q], 0], [[], 1], [[q, a], 1], [[{ author: "c", body: "## 問い\nどうする？" }], 1]]) {
    const gh = fakeGitHub({ issue: { number: 4, status: "答え待ち", comments } });
    await move("置き", "答え待ち");
    assert.deepEqual([gh.issue.status, said(gh).length], [want ? "置き" : "答え待ち", want], JSON.stringify(comments));
  }
});

// 判断材料の節の照らし（順・空・テンプレートのまま）は Pull Request の本文と同じ部品で、tools.test.js の 31 が見る。
test("11 問いは「## 問い」・問いの文・「### 案」と1行1案・判断材料だけで、判断材料が形の節を持つときだけ通る", () => {
  assert.deepEqual(parseQuestion("## 問い\nどうする？\n\n### 案\n- A\n- B\n\n<details><summary>判断材料</summary>\n### 見出し\n</details>"), { text: "どうする？", plans: ["A", "B"], material: "### 見出し" });
  for (const bad of [Q.replace("**案ごと**: A なら…\n", ""), "## 問い\n\n### 案\n- A", "## 問い\nどうする？\n補足の行", "## 問い\nどうする？\n\n### 案\n", "## 問い\nどうする？\n\n### 案\n- A\nB"])
    assert.notDeepEqual(checkQuestion(config.questionTemplate, bad), [], bad);
});

test("11 本物の形（tools/flow-gate/question_template.md）は、書き込む所を埋めれば通り、そのままでは通らない", () => {
  const template = readFileSync(new URL("../question_template.md", import.meta.url), "utf8");
  assert.deepEqual(checkQuestion(template, template.replace(/<(?![a-z/])[^<>]+>/g, "埋めた")), []);
  assert.notDeepEqual(checkQuestion(template, template), []);
});

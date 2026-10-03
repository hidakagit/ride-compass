// ゲートを公開の入口（index.js の fetch）で確かめる。差し替えるのは GitHub（網）だけ。
import assert from "node:assert/strict";
import { before, test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import worker from "../src/index.js";
import { refreshAll } from "../src/refresh.js";
import { answerChoices, check, fieldRefusal, parseQuestion, questionBody } from "../src/rules.js";
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
// ステータスが from から to へ書き換わった出来事。sender は書き換えた者（ボードの手ならユーザー、道具なら Claude）。
const move = (from, to, sender = config.claude) =>
  deliver("projects_v2_item", item({ action: "edited", sender: { login: sender }, changes: { field_value: { field_node_id: "F_1", field_name: "Status", from: from && { name: from }, to: { name: to } } } }));
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
  await move("保留", "進行中", config.gate);
  assert.deepEqual(gh.writes, []);
});

test("入口: ユーザーが書いた issue と段階は未着手で Claude の番、Claude が書いた issue は採否の問いを本文に置いて回答待ちでユーザーの番（入った時点の列は見ない）", async () => {
  let gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "進行中" } });
  await deliver("projects_v2_item", item({ action: "created", sender: { login: "github-project-automation[bot]" } }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", [config.claude]]);
  assert.equal(gh.issue.body ?? "本文", "本文");
  assert.deepEqual(gh.issue.fields, config.project.defaults, "欄の既定値（優先度など）が入る");
  await move(null, "進行中", config.user);
  assert.equal(gh.issue.status, "未着手", "入った直後の「無し」からの変化は見ない");

  gh = fakeGitHub({ issue: { number: 3, authorId: BOT, parent: { number: 1 } } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", [config.claude]]);

  gh = fakeGitHub({ issue: { number: 2, authorId: BOT } });
  await deliver("projects_v2_item", item({ action: "created" }));
  const adoption = config.entry.find((e) => e.question).question;
  assert.deepEqual([gh.issue.status, gh.issue.assignees, comments(gh)], ["回答待ち", [config.user], []]);
  assert.equal(gh.issue.body, `<!-- flow-gate -->\n<!-- 問い\n${questionBody(adoption)}\n-->\n` +
    `[![回答する](${config.urls.gate}/button.svg)](${config.urls.form}/answer?issue=2)\n\n**回答待ち**: ${adoption}\n<!-- /flow-gate -->\n\n本文`);
});

test("入口: 段階の優先度は親の優先度を継ぎ、親に優先度が無ければ既定値が入る（規模など、ほかの欄は継がない）", async () => {
  const priority = config.project.priorityField;
  const parent = { number: 20, authorId: ME, status: "進行中", fields: { [priority]: "高", [config.project.sizeField]: "L" } };
  let gh = fakeGitHub({ issue: { number: 21, authorId: BOT }, parent });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual([gh.issue.status, gh.issue.fields], ["未着手", { [priority]: "高" }]);

  gh = fakeGitHub({ issue: { number: 21, authorId: BOT }, parent: { ...parent, fields: {} } });
  await deliver("projects_v2_item", item({ action: "created" }));
  assert.deepEqual(gh.issue.fields, config.project.defaults);
});

test("Claude は既定と違う欄の値（ユーザーが付けた値）を別の値へ書き換えず、既定の値・値の無い欄・既定を持たない欄は書き換える", () => {
  const priority = config.project.priorityField;
  const fallback = config.project.defaults[priority];
  const other = ["高", "中", "低"].filter((v) => v !== fallback);
  assert.match(fieldRefusal(config, priority, other[0], other[1]), /書き換えません/);
  assert.equal(fieldRefusal(config, priority, other[0], other[0]), null, "同じ値は書き換えにならない");
  assert.equal(fieldRefusal(config, priority, fallback, other[0]), null);
  assert.equal(fieldRefusal(config, priority, undefined, other[0]), null);
  assert.equal(fieldRefusal(config, config.project.sizeField, "L", "S"), null);
});

test("ステータスの書き換えは、Claude の道具の出来事で表にあるものだけが通り、ボードの手での移動と表に無いものは戻す", async () => {
  let gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "進行中", assignees: [config.user] } });
  await move("未着手", "進行中");
  assert.deepEqual([gh.issue.status, gh.issue.assignees, comments(gh)], ["進行中", [config.claude], []], "振り出し。担当者はステータスで決まる");

  gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "未着手" } });
  await move("保留", "未着手", config.user);
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["保留", [config.user]]);
  assert.match(comments(gh)[0], /回答フォームで答えて動かします。「保留」へ戻しました/);

  gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "進行中" } });
  await move("保留", "進行中");
  assert.match(comments(gh)[0], /「保留」から「進行中」へは動かせません/, "Claude でも表に無い移動は戻す");

  gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "回答待ち" } });
  await move("未着手", "回答待ち");
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["未着手", [config.claude]]);
  assert.match(comments(gh)[0], /問いが本文の先頭に無い/);
});

test("振り出しは前提が開いていれば戻し、前提が閉じていれば（見送りでも）通す", async () => {
  let gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "進行中", blockedBy: [{ number: 9, state: "OPEN", stateReason: null }] } });
  await move("未着手", "進行中");
  assert.equal(gh.issue.status, "未着手");
  assert.match(comments(gh)[0], /前提 #9 が閉じていない/);

  gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "進行中", blockedBy: [{ number: 9, state: "CLOSED", stateReason: "NOT_PLANNED" }] } });
  await move("未着手", "進行中");
  assert.deepEqual([gh.issue.status, comments(gh)], ["進行中", []]);
});

test("手で担当者を変えても、ステータスの番へ戻る", async () => {
  const gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "未着手", assignees: [config.user] } });
  await deliver("issues", { action: "assigned", issue: { node_id: "I_1" } });
  assert.deepEqual(gh.issue.assignees, [config.claude]);
});

test("並んで動く別の出来事が先に同じ担当者を入れて書き込みが断られても、読み直して残り（本文）を書き、コメントは重ねない", async () => {
  const gh = fakeGitHub({ issue: { number: 1, authorId: ME, status: "未着手", assignees: [config.claude] }, race: [config.user] });
  await move("保留", "未着手", config.user);
  assert.deepEqual([gh.issue.status, gh.issue.assignees], ["保留", [config.user]]);
  assert.match(gh.issue.body, /回答する.*\n\n\*\*保留\*\*/, "ユーザーの番のボタンが本文の先頭に入る");
  assert.equal(comments(gh).length, 1);
});

const done = "<details><summary>完了の条件</summary>\n\n- [x] 済んだこと\n</details>";
const left = "<details><summary>完了の条件</summary>\n\n- [x] 済んだこと\n- [ ] マージのあとの操作\n</details>";

test("完成で閉じると、完了の条件が揃っていてユーザーの確認が無いときだけ完了になり、残っていれば開き直す。見送りで閉じたものはそのまま完了", async () => {
  const close = (reason, extra) => fakeGitHub({ issue: { number: 8, authorId: ME, status: "未着手", state: "CLOSED", lastClose: [{ stateReason: reason }], ...extra } });
  let gh = close("COMPLETED", { body: done, labels: [] });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.done, "CLOSED"]);

  for (const extra of [{ body: left, labels: [] }, { body: done, labels: [config.confirmLabel] }]) {
    gh = close("COMPLETED", extra);
    await deliver("issues", { action: "closed", issue: { node_id: "I_1" } });
    assert.deepEqual([gh.issue.status, gh.issue.state], ["未着手", "OPEN"]);
    assert.match(comments(gh)[0], /完成として閉じるには、次が残っています/);
  }

  gh = close("NOT_PLANNED", { body: left });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.done, "CLOSED"]);
});

// bin/ask.js が書いたのと同じ、本文の先頭に画面に出ない形で問いを置いた本文。
const asked = (q) => `<!-- flow-gate -->\n<!-- 問い\n${q}\n-->\n<!-- /flow-gate -->\n\n本文`;
const questionId = (html) => /name="q" value="([^"]+)"/.exec(html)[1];
const choicesOf = (html) => [...html.matchAll(/data-text="([^"]*)"/g)].map((m) => m[1]);
const open = async (n) => (await worker.fetch(new Request(`https://gate.test/answer?issue=${n}`), env)).text();
async function answer(n, html, text, note = "", labels) {
  const form = new FormData();
  Object.entries({ issue: String(n), q: questionId(html), choice: String(choicesOf(html).indexOf(text)), note }).forEach(([k, v]) => form.set(k, v));
  for (const l of labels ?? []) form.append("label", l);
  return (await worker.fetch(new Request("https://gate.test/answer", { method: "POST", body: form }), env)).json();
}

test("回答フォームの選択肢は問いによらず表から一律で、「進める」だけが問いの案で分かれ、答えは問い・選択肢・判断材料ごと1つに残る", async () => {
  const q = "## 問い\n重い CI を飛ばしますか\n\n### 案\n- 飛ばす\n- 飛ばさない\n\n<details><summary>判断材料</summary>\n材料の文\n</details>";
  const gh = fakeGitHub({ issue: { number: 4, authorId: ME, status: "回答待ち", assignees: [config.user], body: asked(q) } });
  const html = await open(4);
  assert.deepEqual(choicesOf(html), ["「飛ばす」で進める", "「飛ばさない」で進める", ...config.answers.filter((a) => !a.plans).map((a) => a.text)]);
  assert.match(html, /<\/form><div class="mats"><details open><summary>判断材料<\/summary><div class="md"><p>描いた: 材料の文<\/p><\/div><\/details>/,
    "判断材料は GitHub の描き方で、選択肢と送信の後ろに最初から開いて出す");

  const before = gh.requests.length;
  const r = await answer(4, html, "「飛ばす」で進める");
  assert.deepEqual(gh.requests.slice(before), ["読む", "addComment", "updateProjectV2ItemFieldValue+updateIssue"],
    "送信は、読む・答えを書く（1個）・決定を書く（ステータスと issue の更新の2個）だけ");
  assert.equal(r.label, "「飛ばす」で進める");
  const reply = gh.writes.find((w) => w.op === "addComment");
  assert.equal(reply.as, config.user);
  assert.equal(reply.body, `## 回答\n**重い CI を飛ばしますか**\n\n● **「飛ばす」で進める**\n${choicesOf(html).slice(1).map((c) => `○ ${c}`).join("\n")}\n\n` +
    "次のステータス: 未着手\n\n<details><summary>判断材料</summary>\n\n材料の文\n</details>");
  assert.deepEqual([gh.issue.status, gh.issue.assignees, gh.issue.body], ["未着手", [config.claude], "本文"]);
});

test("選択肢ごとの行き先: 補足が要るものは補足が無ければ断り、完成と見送りは閉じる理由を分ける", async () => {
  const q = questionBody("どうする？");
  const cases = { 進める: ["未着手", "OPEN"], "保留にする（あとで再開できる。補足に理由）": ["保留", "OPEN"], 完成: [config.done, "CLOSED", "COMPLETED"], "見送る（閉じて、再開しない）": [config.done, "CLOSED", "NOT_PLANNED"], "その他（補足に書く）": ["未着手", "OPEN"] };
  for (const [text, [status, state, reason]] of Object.entries(cases)) {
    const gh = fakeGitHub({ issue: { number: 4, authorId: ME, status: "回答待ち", assignees: [config.user], body: asked(q) } });
    const html = await open(4);
    const note = config.answers.find((a) => a.text === text).note;
    if (note) assert.match((await answer(4, html, text)).error, /補足が要ります/, text);
    await answer(4, html, text, note ? "来月まで待つ" : "");
    assert.deepEqual([gh.issue.status, gh.issue.state, gh.issue.assignees], [status, state, state === "OPEN" ? [config.owner[status]] : [config.user]], text);
    if (reason) assert.equal(gh.writes.find((w) => w.stateInput).stateInput.stateReason, reason, text);
  }
  for (const a of config.answers)
    assert.equal(a.text.includes("補足"), Boolean(a.note), `補足の欄の案内は、文言に「補足」とある選択肢を必須と書く: ${a.text}`);
});

test("保留は本文に問いが無くても決まった問いで答えられ、「保留にする」は出ない。Claude の番なら回答フォームは開かない", async () => {
  let gh = fakeGitHub({ issue: { number: 5, authorId: ME, status: "保留", assignees: [config.user] } });
  const html = await open(5);
  assert.match(html, new RegExp(config.questions["保留"]));
  assert.ok(!choicesOf(html).some((c) => config.answers.find((a) => a.text === c).to === "保留"));

  gh = fakeGitHub({ issue: { number: 5, authorId: ME, status: "未着手", assignees: [config.claude] } });
  const closed = await worker.fetch(new Request("https://gate.test/answer?issue=5"), env);
  assert.equal(closed.status, 404);
  assert.match(await closed.text(), /あなたの番ではありません/);

  const q = questionBody("新しい問い？");
  Object.assign(gh.issue, { body: asked(q), status: "回答待ち" });
  await deliver("issues", { action: "edited", issue: { node_id: "I_1" } });
  assert.equal(gh.issue.body, `<!-- flow-gate -->\n<!-- 問い\n${q}\n-->\n[![回答する](${config.urls.gate}/button.svg)](${config.urls.form}/answer?issue=5)\n\n**回答待ち**: 新しい問い？\n<!-- /flow-gate -->\n\n本文`);
  await deliver("issues", { action: "labeled", issue: { node_id: "I_1" } });
  assert.equal(gh.writes.filter((w) => w.op === "updateIssue" && "body" in w).length, 1, "本文の先頭が今の状態と同じなら書き直さない");
});

test("どの道で来た問いでも、材料に本文（印の間を除く）と最近のコメント（新しいものが上）が畳んで載り、issue へのリンクが付く", async () => {
  const comments = Array.from({ length: 7 }, (_, k) => ({ author: "hidakagit-bot", body: `コメント${k + 1}`, createdAt: `2026-10-0${k + 1}T03:04:00Z` }));
  fakeGitHub({ issue: { number: 6, authorId: ME, status: "保留", assignees: [config.user], comments, body: "要約の行\n\n- [ ] 完了の条件" } });
  let html = await open(6);
  const mats = html.slice(html.indexOf("</form>"));
  assert.match(mats, /<details><summary>本文<\/summary><div class="md"><p>描いた: 要約の行\n\n- \[ \] 完了の条件<\/p><\/div><\/details>/);
  const shown = [...mats.matchAll(/描いたコメント: (コメント\d)/g)].map((m) => m[1]);
  assert.deepEqual(shown, ["コメント7", "コメント6", "コメント5", "コメント4", "コメント3"], "最近の5件を新しい順に");
  assert.match(mats, /hidakagit-bot ・ 2026-10-07 12:04/, "書いた人と時刻（日本時間）を添える");
  assert.match(mats, /<details><summary>最近のコメント（新しい順）<\/summary>/);
  assert.match(mats, new RegExp(`<a class="open" href="https://github.com/${config.repository}/issues/6">issue を開く</a>`));
  assert.doesNotMatch(mats, /<details open>|判断材料/, "判断材料の無い問いでは、本文とコメントは畳んだまま出す");

  // Claude の起票は、ゲートが本文の先頭に採否の問いとボタンを置いている。材料の本文はその印の間を除く。
  const adoption = config.entry.find((e) => e.question).question;
  fakeGitHub({ issue: { number: 7, authorId: BOT, status: "回答待ち", assignees: [config.user],
    body: `<!-- flow-gate -->\n<!-- 問い\n${questionBody(adoption)}\n-->\n[![回答する](b)](u)\n\n**回答待ち**: ${adoption}\n<!-- /flow-gate -->\n\n起票の本文` } });
  html = await open(7);
  assert.match(html, /<summary>本文<\/summary><div class="md"><p>描いた: 起票の本文<\/p>/);
  assert.doesNotMatch(html, /回答する|最近のコメント/);
});

test("判断材料を GitHub で描けないときは、判断材料の文字をそのまま出す", async () => {
  fakeGitHub({ markdown: false, issue: { number: 4, authorId: ME, status: "回答待ち", assignees: [config.user],
    body: asked("## 問い\nどうする？\n\n<details><summary>判断材料</summary>\n**太字** と <b>タグ</b>\n</details>") } });
  assert.match(await open(4), /<div class="plain">\*\*太字\*\* と &#60;b&#62;タグ&#60;\/b&#62;<\/div>/);
});

test("回答フォームは置き場のラベルを全部、今の付き方のまま並べ、付け外しがそのまま効いて答えに残る（Project の欄は出さない）", async () => {
  const gh = fakeGitHub({ issue: { number: 7, authorId: BOT, status: "回答待ち", assignees: [config.user], labels: ["規模S"], fields: { [config.project.priorityField]: "中" }, body: asked(questionBody("やりますか？")) } });
  const html = await open(7);
  assert.doesNotMatch(html, /name="field:/, "Project の欄は機械が決めるので出さない");
  assert.match(html, /name="label" value="規模S" checked/);
  assert.match(html, new RegExp(`name="label" value="${config.project.urgentLabel}">`));
  await answer(7, html, "進める", "", [config.project.urgentLabel, config.confirmLabel]);
  assert.deepEqual(gh.issue.labels.sort(), [config.project.urgentLabel, config.confirmLabel].sort());
  assert.match(comments(gh)[0], new RegExp(`\nラベル: \\+${config.project.urgentLabel} \\+${config.confirmLabel} −規模S$`));
  assert.deepEqual(gh.issue.fields, { [config.project.priorityField]: "中" }, "回答フォームは欄を変えない");
});

const pr = (extra) => ({ number: 3, title: "tasks#8: 題名", head: { ref: `${config.code.branchPrefix}8` }, html_url: "https://github.com/pr/3", merged: false, ...extra });
const prEvent = (action, extra) => deliver("pull_request", { repository: { full_name: config.code.repository }, action, pull_request: pr(extra) });
const task = (extra) => fakeGitHub({ issue: { number: 8, authorId: ME, status: "検証中", assignees: [config.claude], body: done, labels: [], ...extra } });

test("Pull Request: 開くと進行中は検証中に、マージされずに閉じると未着手に、マージされると残りが無ければ完了・あれば未着手（表で行けないものは動かさない）", async () => {
  let gh = task({ status: "進行中" });
  await prEvent("opened");
  assert.deepEqual([gh.issue.status, gh.issue.assignees, comments(gh)], ["検証中", [config.claude], []]);

  gh = task({ status: "未着手" });
  await prEvent("opened");
  assert.deepEqual([gh.issue.status, gh.writes], ["未着手", []]);

  gh = task();
  await prEvent("closed");
  assert.equal(gh.issue.status, "未着手");
  assert.match(comments(gh)[0], /マージされずに閉じられました/);

  gh = task();
  await prEvent("closed", { merged: true });
  assert.deepEqual([gh.issue.status, gh.issue.state], [config.done, "CLOSED"]);
  assert.equal(gh.writes.find((w) => w.stateInput)?.stateInput.stateReason, "COMPLETED");
  assert.equal(comments(gh)[0], "Pull Request [#3 tasks#8: 題名](https://github.com/pr/3) をマージしました。完了にします。", "開けるリンク（Markdown の形）で書く");

  for (const [extra, rest] of [[{ body: left }, "マージのあとの操作"], [{ labels: [config.confirmLabel] }, `ユーザーの確認（ラベル「${config.confirmLabel}」）`]]) {
    gh = task(extra);
    await prEvent("closed", { merged: true });
    assert.deepEqual([gh.issue.status, gh.issue.state, gh.issue.assignees], ["未着手", "OPEN", [config.claude]]);
    assert.match(comments(gh)[0], new RegExp(`Claude に戻します。\\n\\n- ${rest.replace(/[()（）「」]/g, ".")}$`));
  }
});

test("子が閉じても、開いた子が残っていれば親は閉じない。最後の子が閉じると（人が閉じても、マージでゲートが閉じても）親を完了で閉じる", async () => {
  const child = { number: 8, authorId: BOT, status: "検証中", assignees: [config.claude], body: done };
  const parent = { number: 20, authorId: ME, status: "進行中", assignees: [config.claude] };
  let gh = fakeGitHub({ issue: { ...child, state: "CLOSED", lastClose: [{ stateReason: "NOT_PLANNED" }] }, parent: { ...parent, siblings: [{ state: "OPEN" }] } });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.issue.status, gh.parent.state, gh.parent.status], [config.done, "OPEN", "進行中"]);

  gh = fakeGitHub({ issue: { ...child, state: "CLOSED", lastClose: [{ stateReason: "NOT_PLANNED" }] }, parent: { ...parent, siblings: [{ state: "CLOSED" }] } });
  await deliver("issues", { action: "closed", issue: { node_id: "I_1" } });
  assert.deepEqual([gh.parent.state, gh.parent.status], ["CLOSED", config.done]);
  assert.equal(gh.writes.find((w) => w.id === "I_P" && w.stateInput).stateInput.stateReason, "COMPLETED");

  gh = fakeGitHub({ issue: child, parent: { ...parent, siblings: [{ state: "CLOSED" }] } });
  await prEvent("closed", { merged: true });
  assert.deepEqual([gh.issue.state, gh.parent.state, gh.parent.status], ["CLOSED", "CLOSED", config.done]);
  assert.match(comments(gh).at(-1), /子の issue が全部閉じた/);
});

test("公開の直後の揃え: 開いた issue を今の規則の姿（ボタン・担当者）へ揃え、揃っていれば何も書かない", async () => {
  const button = (n, status, text) => `[![回答する](${config.urls.gate}/button.svg)](${config.urls.form}/answer?issue=${n})\n\n**${status}**: ${text}`;
  let gh = fakeGitHub({ issue: { number: 3, authorId: ME, status: "保留", assignees: [config.claude] } });
  assert.deepEqual(await refreshAll({ GITHUB_TOKEN: "bot-token" }, config), [{ number: 3, why: ["本文の先頭", "担当者"] }]);
  assert.deepEqual([gh.issue.assignees, gh.issue.body], [[config.user], `<!-- flow-gate -->\n${button(3, "保留", config.questions["保留"])}\n<!-- /flow-gate -->\n\n本文`]);
  const writes = gh.writes.length;
  assert.deepEqual(await refreshAll({ GITHUB_TOKEN: "bot-token" }, config), [], "揃っていれば何も書かない");
  assert.equal(gh.writes.length, writes);
});

test("設定の不変条件: 表・番・入口・選択肢が使う名前はすべて宣言されており、回答フォームは表で行けない先を出さない", () => {
  const people = Object.keys(config.people);
  for (const t of config.transitions) for (const s of [...t.from, ...t.to]) assert.ok(config.statuses.includes(s), s);
  for (const [s, p] of Object.entries(config.owner)) assert.ok(config.statuses.includes(s) && people.includes(p), s);
  for (const e of config.entry) assert.ok(config.statuses.includes(e.to), e.to);
  for (const s of config.coordinator.order) assert.equal(config.owner[s], config.claude, s);
  for (const s of config.transitions.find((t) => t.on === "回答").from) {
    assert.equal(config.owner[s], config.user, `答える状態 ${s} はユーザーの番`);
    const choices = answerChoices(config, { plans: [] }, s);
    assert.ok(choices.length >= 2, s);
    for (const c of choices) assert.ok(check(config, s, c.to, { on: "回答" }).ok, `${s}→${c.to}`);
  }
});

test("問いは「## 問い」・問いの文・「### 案」と1行1案・判断材料だけで、判断材料の中は解釈せず、ほかの行があれば形に合わない", () => {
  assert.deepEqual(parseQuestion("## 問い\nどうする？\n\n### 案\n- A\n- 1 → 40 にする\n\n<details><summary>判断材料</summary>\n### 見出し\n- 箇条\n</details>"),
    { text: "どうする？", plans: ["A", "1 → 40 にする"], material: "### 見出し\n- 箇条" });
  assert.deepEqual(parseQuestion("## 問い\nどうする？"), { text: "どうする？", plans: [], material: "" });
  for (const bad of ["## 問い\n\n### 案\n- A\n", "## 問い\nどうする？\n\n### 選択肢\n- A → 未着手\n- B → 保留\n",
    "## 問い\nどうする？\n補足の行\n", "## 問い\nどうする？\n\n### 案\n", "## 問い\nどうする？\n\n### 案\n- A\nB\n"])
    assert.equal(parseQuestion(bad), null, bad);
});

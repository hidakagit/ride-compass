// ゲートが出来事から事実を読み、表（src/rules.js: decide。行ごとは rules.test.js）で決めて書くことを、ゲートの入口（gate.js: handleEvent）と
// 回答フォームの入口（form.js: answerForm）で確かめる。設定は架空のもの（fake-github.js: config）を渡し、差し替えるのは GitHub（網）だけ。
// 確かめるのは結果（ステータス・担当者・開き閉じ・本文・種類・ボード・取り消した実行・レビュー可能にした PR）。
// ここで見ないもの: 文言・画面の並びと見た目（実物で見比べる）・出来事の署名（GitHub が受け手に求める標準の手順）・道具（bin）の起動。
import assert from "node:assert/strict";
import { before, test } from "node:test";
import { answerForm } from "../src/form.js";
import { handleEvent } from "../src/gate.js";
import { config, fakeGitHub } from "./fake-github.js";

const S = config.status;
const env = { APP_ID: "1", FORM_TOKEN: "form-token" };
before(async () => {
  const { privateKey } = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign"]);
  env.APP_KEY = Buffer.from(await crypto.subtle.exportKey("pkcs8", privateKey)).toString("base64");
});

const tasks = { full_name: config.repository };
const code = { full_name: config.code.repository };
const deliver = (event, payload, sender = config.user) => handleEvent(env, config, event, { sender: { login: sender }, ...payload });
const issueEvent = (action, number = 8, sender) => deliver("issues", { repository: tasks, action, issue: { node_id: `I${number}`, number } }, sender);
const move = (from, to, number = 8) => deliver("projects_v2_item", { repository: tasks, action: "edited", projects_v2_item: { content_type: "Issue", project_node_id: "PVT", content_node_id: `I${number}` },
  changes: { field_value: { field_name: config.project.statusField, from: { name: from }, to: { name: to } } } });
const runEvent = (action, run, path = config.coordinator.workflow) => deliver("workflow_run", { repository: code, action,
  workflow_run: { path: `.github/workflows/${path}`, display_title: `#${run.number} ${run.kind}`, head_branch: `${config.code.branchPrefix}${run.number}`, html_url: "https://x/run", conclusion: run.conclusion ?? null } });
const commented = (gh, number = 8) => deliver("issue_comment", { repository: tasks, action: "created", issue: { node_id: `I${number}`, number }, comment: { body: gh.issues.find((i) => i.number === number).comments.at(-1).body } }, gh.issues.find((i) => i.number === number).comments.at(-1).author);
const said = (gh, by = "gate") => gh.writes.filter((w) => w.op === "addComment" && w.as === by).map((w) => w.body);
const conditions = (...lines) => `要約\n\n<details><summary>完了の条件</summary>\n\n${lines.join("\n")}\n</details>`;
const work = conditions("- [x] 済んだこと", "- [ ] 作ること");
const branch = `${config.code.branchPrefix}8`;

test("担当の実行が起きてから終わるまで、ステータスは進行中（確かめる担当なら検証中）から動かず、終わったら表で決まる", async () => {
  const gh = fakeGitHub({ issues: [{ number: 8, status: S.todo, body: work }], runs: [{ id: 5, number: 8, kind: "作る", status: "queued" }] });
  await runEvent("requested", { number: 8, kind: "作る" });
  assert.equal(gh.issue.status, S.working);
  gh.prs.push({ number: 3, branch, draft: true, head: "h1" });
  gh.checks.h1 = [{ name: "必須", status: "in_progress" }];
  await deliver("pull_request", { repository: code, action: "opened", pull_request: { number: 3, head: { ref: branch } } });
  gh.issue.status = S.ready;
  await move(S.working, S.ready); // ユーザーのボードの移動も、持たれている間は表で決め直すので戻る
  assert.equal(gh.issue.status, S.working);
  Object.assign(gh.runs[0], { status: "completed", conclusion: "success" });
  await runEvent("completed", { number: 8, kind: "作る", conclusion: "success" });
  assert.equal(gh.issue.status, S.ci);

  // 確かめる担当: 検証待ちから持って検証中、CI が通ったあとに下書きへ戻して手放すと未着手。
  const check = fakeGitHub({ issues: [{ number: 8, status: S.ready, body: work }], runs: [{ id: 6, number: 8, kind: "確かめる" }],
    prs: [{ number: 3, branch, draft: false, head: "h1" }], checks: { h1: [{ name: "必須", completedAt: "2026-10-04T01:00:00Z" }] } });
  await runEvent("in_progress", { number: 8, kind: "確かめる" });
  assert.equal(check.issue.status, S.review);
  Object.assign(check.prs[0], { draft: true, convertedAt: "2026-10-04T02:00:00Z" });
  Object.assign(check.runs[0], { status: "completed", conclusion: "success" });
  await runEvent("completed", { number: 8, kind: "確かめる", conclusion: "success" });
  assert.equal(check.issue.status, S.todo);
});

test("どの行にも当たらずに手放したらイレギュラーの問いで回答待ち。問いのコメントを書く時点で、本文の頭にボタンがある", async () => {
  const gh = fakeGitHub({ issues: [{ number: 8, status: S.working, body: work }], runs: [{ id: 5, number: 8, kind: "作る", status: "completed", conclusion: "failure" }] });
  await runEvent("completed", { number: 8, kind: "作る", conclusion: "failure" });
  assert.deepEqual([gh.issue.status, gh.issue.assignees], [S.waiting, [config.user]]);
  const ops = gh.writes.map((w) => w.op);
  const button = gh.writes.findIndex((w) => w.op === "updateIssue" && w.body?.includes(`](${config.urls.form}/answer?issue=8)`));
  assert.ok(button >= 0 && button < ops.indexOf("addComment"), ops.join(","));
  assert.match(said(gh)[0], /^## 問い（イレギュラー）\n/);
});

test("CI待ちのタスクは、CI が通ったら PR をレビュー可能にして検証待ち、落ちたら未着手。変異テストの新しい生き残りは落ちたものと同じ", async () => {
  const at = async (head, extra = {}) => {
    const gh = fakeGitHub({ issues: [{ number: 8, status: S.ci, body: work }], prs: [{ number: 3, branch, draft: true, head, commits: ["h1", head] }],
      checks: { h1: [{ name: "必須" }, { name: config.code.mutation.check, notes: [[config.code.mutation.title, "m1"]] }], ...extra } });
    await runEvent("completed", { number: 8, kind: "CI" }, "ci.yml");
    return [gh.issue.status, gh.readies];
  };
  const mutation = (...m) => ({ name: config.code.mutation.check, notes: [...m.map((x) => [config.code.mutation.title, x]), ["ほかの注記", "x"]] });
  assert.deepEqual(await at("h2", { h2: [{ name: "必須" }, { name: "ほか", conclusion: "failure" }, mutation("m1")] }), [S.ready, ["PR3"]]); // 必須でないチェックは見ない・前の回と同じ生き残りは通す
  assert.deepEqual(await at("h2", { h2: [{ name: "必須" }, mutation("m1", "m2")] }), [S.todo, []]);
  assert.deepEqual(await at("h2", { h2: [{ name: "必須", conclusion: "failure" }] }), [S.todo, []]);
  assert.deepEqual(await at("h2", { h2: [{ name: "必須", conclusion: "cancelled" }] }), [S.todo, []]);
  assert.deepEqual(await at("h2", { h2: [{ name: "必須", conclusion: "skipped" }] }), [S.ready, ["PR3"]]);
  assert.deepEqual(await at("h2", { h2: [{ name: "必須", status: "in_progress" }] }), [S.ci, []]);
  assert.deepEqual(await at("h2", { h2: [{ name: "必須" }, { name: config.code.mutation.check, status: "in_progress" }] }), [S.ci, []]);
  assert.deepEqual(await at("h2", { h2: [] }), [S.ci, []]); // 必須のチェックがまだ起きていない
});

// 回答フォームで答える。choose は画面の入力の名前 → 値（項目ごとの欄は name の頭で選ぶ）。
async function answer(gh, choose) {
  const html = await (await answerForm(new Request("https://form.example/answer?issue=8"), env, config)).text();
  assert.doesNotMatch(html, /次のステータス/);
  const form = new FormData();
  form.set("issue", "8");
  form.set("q", /name="q" value="([^"]+)"/.exec(html)[1]);
  for (const [name, value] of Object.entries(choose)) {
    const real = [...html.matchAll(/name="([^"]+)"/g)].map((m) => m[1]).find((n) => n === name || n.startsWith(name));
    form.set(real, value);
  }
  await answerForm(new Request("https://form.example/answer", { method: "POST", body: form }), env, config);
  await commented(gh);
}
const asked = (kind, extra = "") => ({ author: config.gate.replace("[bot]", ""), body: `## 問い（${kind}）\n問いの文${extra}` });

test("答えは種類ごとの決定を受ける: 見送りは閉じ、保留は保留、続けるは表で決め直す", async () => {
  for (const [kind, choose, want] of [
    ["採否", { decision: "見送り" }, [S.done, "CLOSED"]], ["採否", { decision: "保留" }, [S.hold, "OPEN"]], ["採否", { decision: "続ける" }, [S.todo, "OPEN"]],
    ["イレギュラー", { decision: "続ける" }, [S.todo, "OPEN"]], ["判断", { plan: "A" }, [S.todo, "OPEN"]],
  ]) {
    const gh = fakeGitHub({ issues: [{ number: 8, status: S.waiting, body: work, comments: [asked(kind, kind === "判断" ? "\n\n### 案\n- A\n- B" : "")] }] });
    await answer(gh, choose);
    assert.deepEqual([gh.issue.status, gh.issue.state], want, `${kind} ${JSON.stringify(choose)}`);
  }
});

test("確かめの答え: 全部よいなら条件にチェックが付いて完成で閉じ、よくない項目があれば直す行を足して未着手", async () => {
  const body = conditions("- [x] a", `- [ ] ${config.userCheck}: 画面`, `- [ ] ${config.userCheck}: 地図`);
  let gh = fakeGitHub({ issues: [{ number: 8, status: S.waiting, body, comments: [asked("確かめ")] }] });
  await answer(gh, { good0: "よい", good1: "よい" });
  assert.deepEqual([gh.issue.status, gh.issue.state, gh.issue.lastClose[0].stateReason], [S.done, "CLOSED", "COMPLETED"]);
  gh = fakeGitHub({ issues: [{ number: 8, status: S.waiting, body, comments: [asked("確かめ")] }] });
  await answer(gh, { good0: "よい", good1: "よくない", why1: "線が切れる" });
  assert.deepEqual([gh.issue.status, /- \[x\] 人が見る: 画面/.test(gh.issue.body), /- \[ \] 直す: 線が切れる/.test(gh.issue.body)], [S.todo, true, true]);
});

test("ユーザーのボードの移動: 保留へ入れると持っている担当の実行を取り消し、保留から出すと表で決め直す。完成は条件が全部チェック済みのときだけ", async () => {
  let gh = fakeGitHub({ issues: [{ number: 8, status: S.hold, body: work }], runs: [{ id: 5, number: 8, kind: "作る" }, { id: 4, number: 9, kind: "作る" }] });
  await move(S.working, S.hold);
  assert.deepEqual([gh.issue.status, gh.cancels], [S.hold, [5]]);
  gh = fakeGitHub({ issues: [{ number: 8, status: S.todo, body: work }], prs: [{ number: 3, branch, draft: false, head: "h1" }] });
  await move(S.hold, S.todo);
  assert.equal(gh.issue.status, S.ready);
  gh = fakeGitHub({ issues: [{ number: 8, status: S.done, body: work }] });
  await move(S.todo, S.done);
  assert.deepEqual([gh.issue.status, gh.issue.state, said(gh).length], [S.todo, "OPEN", 1]);
  gh = fakeGitHub({ issues: [{ number: 8, status: S.done, body: conditions("- [x] a") }] });
  await move(S.todo, S.done);
  assert.deepEqual([gh.issue.state, gh.issue.lastClose[0].stateReason], ["CLOSED", "COMPLETED"]);
});

test("閉じる操作: 完成は残りがあれば開き直して決め直し、見送りは完了。完了からは開き直せない", async () => {
  let gh = fakeGitHub({ issues: [{ number: 8, status: S.todo, body: work, state: "CLOSED", lastClose: [{ stateReason: "COMPLETED" }] }] });
  await issueEvent("closed");
  assert.deepEqual([gh.issue.status, gh.issue.state], [S.todo, "OPEN"]);
  gh = fakeGitHub({ issues: [{ number: 8, status: S.todo, body: work, state: "CLOSED", lastClose: [{ stateReason: "NOT_PLANNED" }] }] });
  await issueEvent("closed");
  assert.deepEqual([gh.issue.status, gh.issue.state], [S.done, "CLOSED"]);
  gh = fakeGitHub({ issues: [{ number: 8, status: S.done, body: work, lastClose: [{ stateReason: "NOT_PLANNED" }] }] });
  await issueEvent("reopened");
  assert.deepEqual([gh.issue.status, gh.issue.state], [S.done, "CLOSED"]);
});

test("issue が作られたら種類でボードへ入れる: 対話作業は対話作業のボードだけ、ほかは Actions のボードの入口へ", async () => {
  for (const [issue, want] of [
    [{ type: config.dialog.type, author: "c", parent: 1 }, [["D"], null]],
    [{ type: "要" }, [["A"], S.todo]], // ユーザーの起票
    [{ type: "保", author: "c" }, [["A"], S.todo]], // Claude の改善
    [{ type: "要", author: "c", parent: 1 }, [["A"], S.todo]], // 段階
    [{ type: "要", author: "c" }, [["A"], S.waiting]], // Claude の起こした改善でないもの: 採否の問い
    [{ author: "c" }, [["A"], S.waiting]],
  ]) {
    const gh = fakeGitHub({ issues: [{ number: 8, boards: [], status: null, ...issue }, { number: 1, fields: { [config.project.priorityField]: "上" } }] });
    await issueEvent("opened", 8, issue.author ?? config.user);
    assert.deepEqual([gh.issue.boards, gh.issue.status], want, JSON.stringify(issue));
    if (want[1] === S.waiting) assert.match(said(gh)[0], /^## 問い（採否）\n/);
  }
  // 段階は優先度の欄が空なら親の値を継ぐ。2度目の入口（組み込みの自動追加が後から入れた等）は問いを重ねない。
  const gh = fakeGitHub({ issues: [{ number: 8, boards: [], status: null, type: "要", author: "c" }, { number: 1, fields: { [config.project.priorityField]: "上" } }] });
  await issueEvent("opened", 8, "c");
  await deliver("projects_v2_item", { repository: tasks, action: "created", projects_v2_item: { content_type: "Issue", project_node_id: "PVT", content_node_id: "I8" } }, "automation");
  assert.equal(said(gh).length, 1);
  const stage = fakeGitHub({ issues: [{ number: 8, boards: [], status: null, type: "要", author: "c", parent: 1 }, { number: 1, fields: { [config.project.priorityField]: "上" } }] });
  await issueEvent("opened", 8, "c");
  assert.equal(stage.issue.fields[config.project.priorityField], "上");
});

test("種類は対話作業の境目をまたいで変えられない: またげば元へ戻して1行書き、またがない変更は通す", async () => {
  const at = async (issue) => {
    const gh = fakeGitHub({ issues: [{ number: 8, status: S.todo, ...issue }] });
    await issueEvent(issue.type ? "typed" : "untyped");
    return [gh.issue.type ?? null, said(gh).length];
  };
  const D = config.dialog.type;
  assert.deepEqual(await at({ boards: ["A"], type: D, typeEvents: [{ type: "要" }, { prev: "要", type: D }] }), ["要", 1]);
  assert.deepEqual(await at({ boards: ["A"], type: D, typeEvents: [{ type: "保" }, { prev: "保" }, { type: D }] }), ["保", 1]); // 外してから付けた
  assert.deepEqual(await at({ boards: ["D"], type: "保", status: null, typeEvents: [{ type: D }, { prev: D, type: "保" }] }), [D, 1]);
  assert.deepEqual(await at({ boards: ["D"], type: null, status: null, typeEvents: [{ type: D }, { prev: D }] }), [D, 1]);
  assert.deepEqual(await at({ boards: ["A"], type: "保", typeEvents: [{ type: "要" }, { prev: "要", type: "保" }] }), ["保", 0]);
});

test("担当者は回答待ちと保留のときだけユーザーで、ほかは空。手で変えても戻る", async () => {
  for (const [status, want] of [[S.todo, []], [S.hold, [config.user]]]) {
    const gh = fakeGitHub({ issues: [{ number: 8, status, body: work, assignees: ["u", "c"] }] });
    await issueEvent("assigned");
    assert.deepEqual(gh.issue.assignees, want, status);
  }
});

test("見回りの決め直しの頼みを受けると、持たれていない進行中のタスクを表で決め直す", async () => {
  const gh = fakeGitHub({ issues: [{ number: 8, status: S.working, body: work }], prs: [{ number: 3, branch, draft: false, head: "h1" }] });
  await deliver("repository_dispatch", { repository: tasks, action: "recheck", client_payload: { number: 8 } }, config.claude);
  assert.equal(gh.issue.status, S.ready);
});

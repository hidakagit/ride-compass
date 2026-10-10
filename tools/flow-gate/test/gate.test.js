// ゲートの出入り（src/gate.js の出来事の振り分けと書く順・src/dispatch.js の振り出しと突き合わせ）を、GitHub の代わりの記録係で確かめる。
// どの事実でどう決めるかは decide.test.js が持つ。
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import base from "../flow.config.json" with { type: "json" };
import { dispatch, mismatched } from "../src/dispatch.js";
import { reportHealth, route, settle } from "../src/gate.js";

const config = { ...base, questionTemplate: readFileSync(new URL("../question_template.md", import.meta.url), "utf8") }; // src/index.js と同じ組み方

const OPTIONS = ["未着手", "進行中", "CI待ち", "検証待ち", "検証中", "回答待ち", "保留", "完了", "高", "中", "低"].map((name) => ({ id: name, name }));
// 打たれた呼び出しを順に記録し、読む呼び出しには与えた事実を返す。
function fake({ issue = {}, items = [], runs = [], workflow = "active", last = [], steps = [] } = {}) {
  const calls = [];
  const gql = async (q, v) => {
    calls.push(["gql", q.match(/^\s*(?:query|mutation)[^{]*\{\s*(\w+)/)?.[1] ?? q.slice(0, 20), v]);
    if (q.includes("projectV2(number:$n){id fields")) return { organization: { projectV2: { id: `P${v.n}`, fields: { nodes: [config.fields.status, config.fields.priority].map((name) => ({ id: name, name, options: OPTIONS })) } } } };
    if (q.includes("items(first:100")) return { organization: { projectV2: { items: { pageInfo: { hasNextPage: false }, nodes: items } } } };
    if (q.includes("addProjectV2ItemById")) return { addProjectV2ItemById: { item: { id: "ITEM" } } };
    if (q.includes("t:repository")) return { t: { issue: { id: "I", state: "OPEN", body: "", author: { login: config.user }, issueType: null, assignees: { nodes: [] }, blockedBy: { nodes: [] },
      comments: { nodes: [] }, projectItems: { nodes: [] }, parent: null, timelineItems: { nodes: [] }, ...issue } }, c: { pullRequests: { nodes: [] } } };
    return {};
  };
  const rest = async (method, path, body) => {
    calls.push([method, path, body]);
    // 動いている実行は状態ごとにページで読む。runs は in_progress の状態に、100件ずつのページで返す。
    const page = /status=(\w+)&per_page=100&page=(\d+)/.exec(path);
    if (page) return { workflow_runs: page[1] === "in_progress" ? runs.slice((page[2] - 1) * 100, page[2] * 100) : [] };
    if (path.endsWith(`/workflows/${config.workflow}`)) return { state: workflow };
    if (path.includes("/runs?status=completed")) return { workflow_runs: last };
    if (path.endsWith("/jobs")) return { jobs: [{ steps }] };
    return {};
  };
  return { gh: { gql, rest }, calls };
}
const item = (number, status, more = {}) => ({ project: { number: config.boards.actions }, status: { name: status }, priority: null, start: null,
  content: { number, state: "OPEN", issueType: null, labels: { nodes: [] }, blockedBy: { nodes: [] } }, ...more });
const run = (number, kind) => ({ id: number * 10, status: "in_progress", display_title: `#${number} ${kind}` });

test("出来事の振り分け: ゲート自身・Claude の本文の書き換え・ほかの動きは受けない", async () => {
  const { gh } = fake();
  const tasks = { full_name: config.tasks };
  const code = { full_name: config.code };
  assert.deepEqual(await route(gh, config, "issues", { action: "opened", sender: { login: config.gateBot }, issue: { number: 5 }, repository: tasks }), { numbers: [] });
  assert.deepEqual(await route(gh, config, "issues", { action: "edited", sender: { login: config.claude }, issue: { number: 5 }, repository: tasks }), { numbers: [] });
  assert.deepEqual(await route(gh, config, "issues", { action: "milestoned", sender: { login: config.user }, issue: { number: 5 }, repository: tasks }), { numbers: [] });
  assert.deepEqual(await route(gh, config, "issue_comment", { action: "created", sender: { login: config.user }, issue: { number: 5 }, repository: tasks }), { numbers: [5] });
  assert.deepEqual(await route(gh, config, "pull_request", { action: "converted_to_draft", sender: { login: config.claude }, pull_request: { head: { ref: `${config.branchPrefix}12` } }, repository: code }), { numbers: [12] });
  assert.deepEqual(await route(fake({ items: [item(2, "検証中")] }).gh, config, "schedule", {}), { numbers: [2], free: true });
  assert.deepEqual(await route(gh, config, "workflow_run", { action: "completed", sender: { login: config.gateBot }, workflow_run: { path: `.github/workflows/${config.workflow}`, display_title: "#9 作る" }, repository: code }),
    { numbers: [9], free: true });
});

test("書く順: 本文のボタンは問いより先、ボードへ入れてから欄、閉じるのは最後", async () => {
  // Claude が起こした要望（入口で採否を問う）。
  const { gh, calls } = fake({ issue: { author: { login: config.claude }, issueType: { name: "要望" }, body: "- [ ] 作る\n" } });
  const d = await settle(gh, config, 4, Promise.resolve([]));
  assert.equal(d.status, "回答待ち");
  const at = (s) => calls.findIndex(([m, p, b]) => `${m} ${p}`.includes(s) || (s === "status" && b?.v === "回答待ち") || (s === "add" && p === "addProjectV2ItemById"));
  assert.ok(at("PATCH /repos") < at("POST /repos/ridecompass/ride-compass-tasks/issues/4/comments"));
  assert.ok(at("POST /repos/ridecompass/ride-compass-tasks/issues/4/comments") < at("add"));
  assert.ok(at("add") < at("status"));
  assert.ok(at("status") < at("POST /repos/ridecompass/ride-compass-tasks/issues/4/assignees"));
  assert.match(calls[at("PATCH /repos")][2].body, /flow-gate/);

  // 残りが無い → 欄を書いてから閉じる。
  const done = fake({ issue: { body: "- [x] 作る\n", projectItems: { nodes: [{ id: "IT", project: { number: config.boards.actions }, status: { name: "進行中" } }] } } });
  await settle(done.gh, config, 4, Promise.resolve([]));
  assert.deepEqual(done.calls.at(-1), ["PATCH", "/repos/ridecompass/ride-compass-tasks/issues/4", { state: "closed", state_reason: "completed" }]);
});

test("突き合わせ: 実行の有無と作業のステータスが食い違うタスクと CI待ちだけを決め直す", async () => {
  const { gh } = fake({ items: [item(1, "進行中"), item(2, "検証中"), item(3, "未着手"), item(4, "CI待ち"), item(5, "未着手"), item(6, "検証待ち")], runs: [run(1, "作る"), run(3, "作る")] });
  assert.deepEqual(await mismatched(gh, config), [2, 3, 4]);
});

test("突き合わせ: 動いている実行が100件を超えても、後ろのページの実行を落とさない（約束25）", async () => {
  const many = Array.from({ length: 150 }, (_, i) => run(1000 + i, "作る"));
  const { gh } = fake({ items: [item(1149, "進行中")], runs: many });
  assert.deepEqual(await mismatched(gh, config), []);
});

test("振り出し: 最後の担当が利用の上限で止まったら、その終わりから決まった間は振り出さない", async () => {
  const items = [item(1, "未着手")];
  const ago = (minutes) => ({ id: 5, conclusion: "failure", updated_at: new Date(Date.now() - minutes * 60e3).toISOString() });
  const quota = [{ name: config.quotaStep, conclusion: "failure" }];
  const held = await dispatch(fake({ items, last: [ago(1)], steps: quota }).gh, config, []);
  assert.deepEqual(held.picked, []);
  assert.match(held.stopped, /利用の上限か認証で止まったため/);
  assert.equal((await dispatch(fake({ items, last: [ago(config.pauseMinutes + 1)], steps: quota }).gh, config, [])).picked.length, 1);
  assert.equal((await dispatch(fake({ items, last: [ago(1)], steps: [{ name: config.quotaStep, conclusion: "success" }] }).gh, config, [])).picked.length, 1);
});

test("振り出し: 止めたら振り出さず、枠の空きの数まで急ぎ・優先度・番号の順に起こす", async () => {
  const items = [item(8, "未着手"), item(7, "未着手", { priority: { name: "低" } }), item(9, "未着手", { priority: { name: "高" } }), item(6, "未着手"), item(5, "検証待ち"),
    item(4, "未着手", { content: { ...item(4).content, labels: { nodes: [{ name: config.urgentLabel }] } } }), item(3, "未着手", { content: { ...item(3).content, blockedBy: { nodes: [{ state: "OPEN" }] } } })];
  const busy = Array.from({ length: config.slots.作る - 2 }, (_, i) => ({ id: i, number: 100 + i, kind: "作る" }));
  const off = await dispatch(fake({ items, workflow: "disabled_manually" }).gh, config, busy);
  assert.deepEqual(off.picked, []);
  assert.match(off.stopped, /無効/);
  assert.deepEqual((await dispatch(fake({ items }).gh, config, busy)).picked.map((p) => `${p.issue} ${p.kind}`), ["4 作る", "9 作る", "5 確かめる"]);
});

test("状況の更新: 盤面に表れない事実（突き合わせの失敗・振り出しの止まり・決め直したタスク）を、変わったときだけ足す", async () => {
  // latest は最新の状況の更新。書いたもの（状態と本文）を返す。
  const write = async (latest, facts) => {
    const { gh, calls } = fake();
    const gql = gh.gql;
    gh.gql = async (q, v) => (q.includes("statusUpdates") ? { node: { statusUpdates: { nodes: latest ? [latest] : [] } } } : gql(q, v));
    await reportHealth(gh, config, facts);
    return calls.filter(([, name]) => name === "createProjectV2StatusUpdate").map(([, , v]) => `${v.s} ${v.b.split("\n")[0]}`);
  };
  const ok = { status: "ON_TRACK", body: "ゲートは盤面を保っている（定時の突き合わせが通っている）" };
  assert.deepEqual(await write(ok, {}), [], "変わらなければ書かない");
  assert.deepEqual(await write(null, {}), [], "まだ何も無く、保っているだけなら書かない");
  assert.deepEqual(await write(ok, { error: new Error("落ちた") }), ["OFF_TRACK ゲートの定時の突き合わせが失敗している（盤面が事実とずれていても直らない）"]);
  assert.deepEqual(await write({ status: "OFF_TRACK", body: "ゲートの定時の突き合わせが失敗している（盤面が事実とずれていても直らない）\n\n誤り: 別" }, { error: new Error("また") }), [], "失敗が続く間は重ねない");
  assert.deepEqual(await write({ status: "OFF_TRACK", body: "ゲートの定時の突き合わせが失敗している（盤面が事実とずれていても直らない）" }, {}), [`ON_TRACK ${ok.body}`], "戻ったら書く");
  assert.deepEqual(await write(ok, { stopped: "担当のワークフロー（Claude Task）が無効" }), ["AT_RISK 振り出しを止めている: 担当のワークフロー（Claude Task）が無効"]);
  assert.deepEqual(await write(ok, { fixed: [12] }), [`ON_TRACK ${ok.body}`], "決め直したタスクがあれば書く");
});

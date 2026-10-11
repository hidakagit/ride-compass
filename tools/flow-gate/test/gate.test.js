// ゲートを入口から、tasks#788 の要求とユーザーと決めた約束（tasks#799）で確かめる。出来事は受け箱（src/inbox.js: Inbox）に入れて本物と同じ処理
// （src/flow.js: handle）で、回答フォームは HTTP の要求（src/form.js: answerForm）で動かし、ボード・コメント・本文・PR・ラベル・実行・状況の更新を見る。
// 期待は要求の文から書く（各行・各 assert の名前）。GitHub の代わりの world は、置き場の issue・ボード・作業ブランチの PR・担当の実行を持つ。
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import base from "../flow.config.json" with { type: "json" };
import { handle } from "../src/flow.js";
import { answerForm } from "../src/form.js";
import { Inbox } from "../src/inbox.js";
import { Patrol } from "../src/patrol.js";
import { askText, withButton } from "../src/questions.js"; // 本物のボタンと、ゲートの問いの形を入力に使う

const config = { ...base, questionTemplate: readFileSync(new URL("../question_template.md", import.meta.url), "utf8"), slots: { 作る: 2, 確かめる: 1 } };
const OPTIONS = ["未着手", "進行中", "CI待ち", "検証待ち", "検証中", "回答待ち", "保留", "完了", "高", "中", "低"].map((name) => ({ id: name, name }));
const tasks = { full_name: config.tasks };
const code = { full_name: config.code };
const names = (list) => ({ nodes: list.map((name) => ({ name })) });

function world(list, { workflow = "active", last = [], steps = [] } = {}) {
  const w = { issues: new Map(), runs: [], writes: [], updates: [] };
  for (const i of list) w.issues.set(i.n, { state: "OPEN", reason: null, body: "- [ ] 作る\n", author: config.user, type: null, assignees: [], blockedBy: [],
    comments: [], status: null, priority: null, start: null, board: "actions", parent: null, labels: [], pr: null, ...i });
  w.at = (n) => w.issues.get(n);
  const item = (i) => (i.board ? [{ id: `IT${i.n}`, project: { number: config.boards[i.board] }, status: i.status && { name: i.status },
    priority: i.priority && { name: i.priority }, start: i.start && { text: i.start } }] : []);
  const blocked = (i) => ({ nodes: i.blockedBy.map((b) => ({ state: w.at(b).state })) });
  const pull = (i, p) => ({ id: `PR${i.n}`, state: p.state ?? "OPEN", isDraft: p.draft, merged: Boolean(p.merged), mergeCommit: { statusCheckRollup: p.mergeChecks && { state: p.mergeChecks } },
    commits: { nodes: [{ commit: { oid: `c${i.n}`, committedDate: "2026-10-11T00:00:00Z", statusCheckRollup: p.checks && { state: p.checks } } }] },
    timelineItems: { nodes: p.drafted ? [{ createdAt: "2026-10-11T01:00:00Z" }] : [] } });
  const gql = async (q, v) => {
    if (q.includes("fields(first:30")) return { organization: { projectV2: { id: `P${v.n}`, fields: { nodes: [config.fields.status, config.fields.priority].map((name) => ({ id: name, name, options: OPTIONS })) } } } };
    if (q.includes("items(first:100")) return { organization: { projectV2: { items: { pageInfo: { hasNextPage: false }, nodes: [...w.issues.values()].filter((i) => i.board === "actions")
      .map((i) => ({ ...item(i)[0], content: { number: i.n, state: i.state, issueType: i.type && { name: i.type }, labels: names(i.labels), blockedBy: blocked(i) } })) } } } };
    if (q.includes("blocking(")) return { repository: { issue: { blocking: { nodes: [...w.issues.values()].filter((i) => i.blockedBy.includes(v.n)).map((i) => ({ number: i.n, state: i.state })) } } } };
    if (q.includes("bodyHTML")) { // 回答フォームの読み（src/form.js）
      const i = w.at(v.i);
      return { repository: { labels: names(["急ぎ", "要確認"]), issue: { id: `I${i.n}`, title: "タスク", url: `https://github.test/${i.n}`, body: i.body, labels: names(i.labels),
        comments: { nodes: i.comments.map((body) => ({ body, bodyHTML: body, url: "https://github.test/c", createdAt: "2026-10-11T00:00:00Z", author: { login: "x" } })) } } } };
    }
    if (q.includes("t:repository")) {
      const i = w.at(v.n);
      return { t: { issue: { id: `I${i.n}`, state: i.state, stateReason: i.reason, body: i.body, author: { login: i.author }, issueType: i.type && { name: i.type },
        assignees: { nodes: i.assignees.map((login) => ({ login })) }, blockedBy: blocked(i), comments: { nodes: i.comments.map((body) => ({ body })) }, projectItems: { nodes: item(i) },
        parent: i.parent && { projectItems: { nodes: item(w.at(i.parent)) } }, timelineItems: { nodes: (i.typeChanges ?? []).map(([a, b]) => ({ prevIssueType: { name: a }, issueType: { name: b } })) } } },
      c: { pullRequests: { nodes: i.pr ? [pull(i, i.pr)] : [] } } };
    }
    if (q.includes("statusUpdates")) return { node: { statusUpdates: { nodes: w.updates.slice(-1) } } };
    if (q.includes("node(id:")) return { node: { number: Number(v.id.slice(1)) } };
    if (q.includes("updateProjectV2ItemFieldValue")) return void (w.at(Number(v.i.slice(2)))[v.f === config.fields.status ? "status" : "priority"] = v.v);
    if (q.includes("addProjectV2ItemById")) {
      w.at(Number(v.c.slice(1))).board = Object.keys(config.boards).find((k) => v.p === `P${config.boards[k]}`);
      return { addProjectV2ItemById: { item: { id: `IT${v.c.slice(1)}` } } };
    }
    if (q.includes("markPullRequestReadyForReview")) return void (w.at(Number(v.id.slice(2))).pr.draft = false);
    if (q.includes("createProjectV2StatusUpdate")) return void w.updates.push({ status: v.s, body: v.b });
    throw new Error(`知らない問い合わせ: ${q.slice(0, 80)}`);
  };
  const rest = async (method, path, body) => {
    let m;
    if (path.endsWith(`/workflows/${config.workflow}`)) return { state: workflow };
    if (path.includes("/runs?status=completed&per_page=1")) return { workflow_runs: last };
    if (path.endsWith("/jobs")) return { jobs: [{ steps }] };
    if (path.endsWith("/dispatches")) return void w.runs.push({ id: 100 + w.runs.length, display_title: `#${body.inputs.issue} ${body.inputs.kind} ${body.inputs.key}` });
    if ((m = /\/actions\/runs\/(\d+)\/cancel$/.exec(path))) return void w.writes.push(["取り消し", Number(m[1])]);
    if ((m = /\/commits\/(\w+)\/pulls$/.exec(path))) return [...w.issues.values()].filter((i) => i.pr?.sha === m[1]).map((i) => ({ head: { ref: `${config.branchPrefix}${i.n}` } }));
    if ((m = /\/commits\/c(\d+)\/check-runs/.exec(path))) return { check_runs: w.at(Number(m[1])).survivors ? [{ id: Number(m[1]), completed_at: "2026-10-11T00:00:00Z" }] : [] };
    if ((m = /\/check-runs\/(\d+)\/annotations/.exec(path))) return w.at(Number(m[1])).survivors.map((message) => ({ title: "テストが気づかない書き換え", path: "src/a.js", message }));
    if ((m = /\/issues\/(\d+)\/labels(?:\/(.+))?$/.exec(path))) {
      const i = w.at(Number(m[1]));
      return void (i.labels = m[2] ? i.labels.filter((l) => l !== decodeURIComponent(m[2])) : [...i.labels, ...body.labels]);
    }
    const i = w.at(Number(/\/issues\/(\d+)/.exec(path)[1]));
    if (path.endsWith("/comments")) return void (i.comments.push(body.body), w.writes.push(["コメント", i.n, body.body.split("\n")[0]]));
    if (body.body !== undefined) w.writes.push(["本文", i.n]);
    return void Object.assign(i, body.state ? { state: body.state.toUpperCase(), reason: body.state_reason?.toUpperCase() ?? null } : {}, body.body !== undefined ? { body: body.body } : {},
      body.type ? { type: body.type } : {}, body.assignees ? { assignees: body.assignees } : {});
  };
  w.gh = { gql, rest };
  // 置き場は Durable Object の置き場と同じ口（get・put・delete・前方一致の list）をメモリで持つ。受け箱と見回りは本物。
  const memory = new Map();
  const storage = { get: async (k) => memory.get(k), put: async (k, v) => void memory.set(k, v), delete: async (k) => [k].flat().forEach((x) => memory.delete(x)),
    list: async ({ prefix }) => new Map([...memory].filter(([k]) => k.startsWith(prefix)).sort(([a], [b]) => (a < b ? -1 : 1))) };
  const patrol = new Patrol(storage);
  w.inbox = new Inbox(storage, (name, payload) => (w.fail ? Promise.reject(w.fail) : handle(w.gh, { patrol, inbox: w.inbox }, config, name, payload)));
  w.push = ([name, payload]) => w.inbox.push(name, payload);
  w.send = async (event) => (await w.push(event), w.inbox.drain(config.retries));
  w.titles = () => w.runs.map((r) => r.display_title.split(" ").slice(0, 2).join(" "));
  w.run = (n) => w.runs.findLast((r) => r.display_title.startsWith(`#${n} `));
  return w;
}
const ev = {
  run: (r, action) => ["workflow_run", { action, sender: { login: config.gateBot }, repository: code, workflow_run: { id: r.id, path: `.github/workflows/${config.workflow}`, display_title: r.display_title } }],
  ci: (branch, sha = "x") => ["workflow_run", { action: "completed", sender: { login: config.user }, repository: code, workflow_run: { id: 1, path: ".github/workflows/ci.yml", head_branch: branch, head_sha: sha } }],
  comment: (n, login = config.user) => ["issue_comment", { action: "created", sender: { login }, issue: { number: n }, repository: tasks }],
  issue: (n, action, login = config.user, more = {}) => ["issues", { action, sender: { login }, issue: { number: n, body: more.body }, changes: more.changes, repository: tasks }],
  pr: (n, action) => ["pull_request", { action, sender: { login: config.user }, repository: code, pull_request: { head: { ref: `${config.branchPrefix}${n}` } } }],
  move: (n) => ["projects_v2_item", { action: "edited", sender: { login: config.user }, changes: { field_value: { field_name: config.fields.status } },
    projects_v2_item: { project_node_id: `P${config.boards.actions}`, content_node_id: `I${n}` } }],
  schedule: () => ["schedule", {}],
};
const head = (i) => i.comments.at(-1)?.split("\n")[0] ?? null;
const QUESTION = config.questionTemplate; // 形どおりの判断の問い
const ANSWER = (line) => `## 回答\n**${QUESTION.split("\n")[1]}**\n\n${line}`;
const CONFIRM = "- [x] 作る\n- [ ] ユーザーが確かめる: 見た目\n";
const ASKED = (kind) => askText(kind, config.questionTemplate); // ゲートが出す問い

test("R2・R17・R14・K1: 振り出したその場で進行中（順番待ちを含む）。同時に届いた出来事でも、1つのタスクに担当は1人で、枠の数まで急ぎ・優先度の順", async () => {
  const w = world([{ n: 1, status: "未着手", priority: "低" }, { n: 2, status: "未着手", labels: [config.urgentLabel] }, { n: 3, status: "未着手", priority: "高" },
    { n: 4, status: "未着手", blockedBy: [9] }, { n: 5, status: "未着手", start: "2099-01-01" }, { n: 9, status: "保留" }]);
  await Promise.all([w.push(ev.schedule()), w.push(ev.schedule()), w.push(ev.comment(1))]);
  await w.inbox.drain(config.retries);
  assert.deepEqual(w.titles().sort(), ["#2 作る", "#3 作る"]);
  assert.deepEqual([1, 2, 3, 4, 5, 9].map((n) => w.at(n).status), ["未着手", "進行中", "進行中", "未着手", "未着手", "保留"]);
  await w.send(ev.run(w.run(2), "requested"));
  await w.send(ev.run({ id: 7, display_title: "#2 作る" }, "completed"));
  assert.equal(w.at(2).status, "進行中", "別の実行（手で起こした実行）の終わりで、今の担当を手放さない");
  await w.send(ev.run(w.run(3), "completed"));
  await w.send(ev.run(w.run(3), "in_progress"));
  assert.deepEqual([w.at(3).status, head(w.at(3))], ["回答待ち", "## 問い（イレギュラー）"], "終わったあとに届いた始まりの知らせで持ち直さない");
});

test("R3・決め1・決め7: 担当の実行が終わったら、表の上から最初に当たる行で決める", async () => {
  const verify = { status: "検証待ち", pr: { draft: false, checks: "SUCCESS" } };
  const rows = [
    // [要求, 始まりのタスク, 終わったときの事実, ステータス, 起きた担当の数, 最後のコメントの頭]
    ["R3a 答えの無い問い", {}, { comments: [QUESTION] }, "回答待ち", 1, "## 問い（判断）"],
    ["R3b 下書きの PR の CI が終わっていない", {}, { pr: { draft: true, checks: "PENDING" } }, "CI待ち", 1, null],
    ["R3c・原則の点検の3 下書きでない PR の CI が通った → 検証待ち → 確かめる担当", {}, { pr: { draft: false, checks: "SUCCESS" } }, "検証中", 2, null],
    ["R3d 確かめる担当が下書きへ戻した（差し戻し）→ 作る担当", verify, { pr: { draft: true, checks: "SUCCESS", drafted: true } }, "進行中", 2, null],
    ["確かめる担当が、マージも差し戻しも問いもせずに手放した → イレギュラー", verify, {}, "回答待ち", 1, "## 問い（イレギュラー）"],
    ["R3e 条件が全部済んだ → 完成で閉じる", {}, { body: "- [x] 作る\n" }, "完了", 1, null],
    ["R3f 残りがユーザーの確かめだけ", {}, { body: CONFIRM }, "回答待ち", 1, "## 問い（確かめ）"],
    ["R3g 開いた前提", {}, { blockedBy: [9] }, "未着手", 1, null],
    ["R3g 未来の着手可能日時", {}, { start: "2099-01-01" }, "未着手", 1, null],
    ["決め3 作る担当が CI の結果のあとに持って見た生き残りは通す → 検証待ち → 確かめる担当", {}, { pr: { draft: true, checks: "SUCCESS" }, survivors: ["書き換え"] }, "検証中", 2, null],
    ["R3h どれでもない（落ちた）→ 黙って振り出し直さない", {}, {}, "回答待ち", 1, "## 問い（イレギュラー）"],
    ["決め1 マージのあとの残り", {}, { pr: { state: "MERGED", merged: true, mergeChecks: "SUCCESS" } }, "進行中", 2, null],
    ["マージのコミットの CI がまだ（本番に出る前に確かめを問わない）", {}, { body: CONFIRM, pr: { state: "MERGED", merged: true, mergeChecks: "PENDING" } }, "CI待ち", 1, null],
  ];
  for (const [name, start, facts, status, runs, comment] of rows) {
    const w = world([{ n: 1, status: "未着手", ...start }, { n: 9, status: "保留" }]);
    await w.send(ev.schedule());
    const run = w.run(1);
    await w.send(ev.run(run, "requested"));
    assert.equal(w.at(1).status, start.status ? "検証中" : "進行中", name);
    Object.assign(w.at(1), facts);
    await w.send(ev.run(run, "completed"));
    assert.deepEqual([w.at(1).status, w.runs.length, head(w.at(1))], [status, runs, comment], name);
    if (status === "回答待ち") assert.deepEqual([w.at(1).assignees, w.at(1).body.startsWith("<!-- flow-gate -->")], [[config.user], true], `${name}: ユーザーの番で、本文の頭に回答のボタン`);
  }
});

test("出来事1つで決め直す（R2・R4〜R9・R16・K2・K5・決め3・決め5・決め7・Claude の本文の書き換え）", async () => {
  const merged = { state: "MERGED", merged: true, mergeChecks: "SUCCESS", sha: "m1" };
  const rows = [
    // [要求, タスク, 担当が付いた後に変わる事実（無ければ担当なし）, 出来事, 期待]
    ["R4 PR の CI が落ちた → 未着手 → 同じ枝で直す作る担当", { status: "CI待ち", pr: { draft: true, checks: "FAILURE" } }, null, ev.ci(`${config.branchPrefix}1`), { status: "進行中", runs: ["#1 作る"] }],
    ["決め3 新しい変異テストの生き残り → 落ちたものと同じ", { status: "CI待ち", pr: { draft: true, checks: "SUCCESS" }, survivors: ["書き換え"] }, null, ev.ci(`${config.branchPrefix}1`), { status: "進行中", runs: ["#1 作る"] }],
    ["R4 PR の CI が通った → PR をレビュー可能にして検証待ち → 確かめる担当", { status: "CI待ち", pr: { draft: true, checks: "SUCCESS" } }, null, ev.ci(`${config.branchPrefix}1`), { status: "検証中", draft: false }],
    ["原則の点検の1 master の CI が落ちた → 本番に出ていないので確かめを問わず CI待ち", { status: "CI待ち", body: CONFIRM, pr: { ...merged, mergeChecks: "FAILURE" } }, null, ev.ci(config.base, "m1"), { status: "CI待ち", comment: null }],
    ["K2・R12 確かめの答えに項目が無い → 済ませず、また確かめを問う", { status: "回答待ち", body: CONFIRM, comments: [ASKED("確かめ"), "## 回答\n**完成にしてよいですか？**\n\n補足: 見た"] }, null, ev.comment(1),
      { state: "OPEN", status: "回答待ち", comment: "## 問い（確かめ）" }],
    ["決め6 前からある Claude の割り当ては外し、保留ではユーザーだけ", { status: "保留", assignees: [config.claude] }, null, ev.comment(1), { assignees: [config.user] }],
    ["R6 見送り（Close as not planned）で閉じたものは閉じたまま", { status: "完了", state: "CLOSED", reason: "NOT_PLANNED" }, null, ev.issue(1, "closed"), { state: "CLOSED" }],
    ["A 対話作業のボードは、開発機のセッションが触っていることを持たない（作業のステータスを書かない）", { status: "未着手", board: "dialog", type: config.dialogType, pr: { draft: true, checks: "PENDING" } }, null,
      ev.comment(1), { status: "未着手" }],
    ["R8 マージのコミットの master の CI が終わった → 確かめの問い", { status: "CI待ち", body: CONFIRM, pr: merged }, null, ev.ci(config.base, "m1"), { status: "回答待ち", comment: "## 問い（確かめ）" }],
    ["R8・決め7 CI が通ったあとに PR が下書きへ戻された（差し戻し）→ 未着手 → 作る担当", { status: "検証待ち", pr: { draft: true, checks: "SUCCESS", drafted: true } }, null, ev.pr(1, "converted_to_draft"), { status: "進行中", runs: ["#1 作る"] }],
    ["R5・決め1・決め6 判断の答えで続ける → 表で決め直して未着手 → 作る担当（ユーザーの番を出たら割り当てを外す）", { status: "回答待ち", assignees: [config.user], comments: [QUESTION, ANSWER("補足: A で")] }, null, ev.comment(1),
      { status: "進行中", runs: ["#1 作る"], assignees: [] }],
    ["R5・決め6 答えが保留 → 保留（ユーザーの番）", { status: "回答待ち", comments: [QUESTION, ANSWER("回答: 保留する")] }, null, ev.comment(1), { status: "保留", assignees: [config.user] }],
    ["R6・決め5 ユーザーが保留から出す → 表で決め直す", { status: "未着手" }, null, ev.move(1), { status: "進行中", runs: ["#1 作る"] }],
    ["R6 条件が全部済んでユーザーが完了へ動かす → 受ける（完成）", { status: "完了", body: "- [x] 作る\n" }, null, ev.move(1), { status: "完了", state: "CLOSED", reason: "COMPLETED" }],
    ["K2 条件が残ったまま完成で閉じた → 開き直す", { status: "保留", state: "CLOSED", reason: "COMPLETED" }, null, ev.issue(1, "closed"), { state: "OPEN" }],
    ["R7 担当が持っているタスクをユーザーが保留へ → その実行を取り消す", { status: "未着手" }, { status: "保留" }, ev.move(1), { status: "保留", cancels: [100], assignees: [config.user] }],
    ["R2・R13・K4 担当が付いている間は決め直さず、その間に出した問いのボタンも消さない", { status: "未着手" }, { comments: [QUESTION], body: withButton("- [ ] 作る\n", config, 1) }, ev.comment(1),
      { status: "進行中", runs: ["#1 作る"], button: true }],
    ["R9・R13 Claude が起こした要望は採否を問い、本文の頭のボタンは問いより先に書く", { author: config.claude, type: "要望", board: null }, null, ev.issue(1, "opened", config.claude),
      { status: "回答待ち", comment: "## 問い（採否）", writes: ["本文", "コメント"] }],
    ["R16 対話作業は別のボードへ入れ、振り出さない", { type: config.dialogType, board: null }, null, ev.issue(1, "opened"), { board: "dialog", status: "未着手", runs: [] }],
    ["K5 段階は親の優先度を継ぐ", { board: null, parent: 4 }, null, ev.issue(1, "opened"), { priority: "高" }],
    ["R16 対話作業の境目をまたがない種類の変更は通す", { status: "保留", type: "要望", typeChanges: [["不具合", "要望"]] }, null, ev.issue(1, "typed"), { type: "要望" }],
    ["R16 対話作業の境目をまたぐ種類の変更は戻す", { status: "未着手", board: "dialog", type: "不具合", typeChanges: [[config.dialogType, "不具合"]] }, null, ev.issue(1, "typed"), { type: config.dialogType }],
    ["Claude が本文の完了の条件に印を付けた → 決め直す", { status: "未着手", body: "- [x] 作る\n" }, null, ev.issue(1, "edited", config.claude, { body: "- [x] 作る\n", changes: { body: { from: "- [ ] 作る\n" } } }), { status: "完了" }],
    ["回答のボタンだけを書き足した本文の書き換え → 受けない（問いの前にボタンを消さない）", { status: "未着手", body: withButton("- [ ] 作る\n", config, 1) }, null,
      ev.issue(1, "edited", config.claude, { body: withButton("- [ ] 作る\n", config, 1), changes: { body: { from: "- [ ] 作る\n" } } }), { status: "未着手", runs: [] }],
  ];
  for (const [name, task, change, event, want] of rows) {
    const w = world([{ n: 1, ...task }, { n: 4, status: "保留", priority: "高" }]);
    if (change) await w.send(ev.schedule()).then(() => w.send(ev.run(w.run(1), "requested")));
    Object.assign(w.at(1), change);
    await w.send(event);
    const i = w.at(1);
    const got = { status: i.status, state: i.state, reason: i.reason, type: i.type, board: i.board, priority: i.priority, assignees: i.assignees, comment: head(i), runs: w.titles(),
      draft: i.pr?.draft, button: i.body.startsWith("<!-- flow-gate -->"),
      cancels: w.writes.filter(([k]) => k === "取り消し").map(([, id]) => id), writes: w.writes.filter(([, n]) => n === 1).map(([k]) => k) };
    assert.deepEqual(Object.fromEntries(Object.keys(want).map((k) => [k, got[k]])), want, name);
  }
});

test("前提が閉じたら、後ろで待っていたタスクも決め直して振り出す", async () => {
  const w = world([{ n: 6, status: "未着手", blockedBy: [7] }, { n: 7, status: "回答待ち", state: "CLOSED" }]);
  await w.send(ev.issue(7, "closed"));
  assert.deepEqual([w.at(6).status, w.titles()], ["進行中", ["#6 作る"]]);
});

test("K6・受け箱・状況の更新: 止めたら振り出さず理由を出す。処理が落ちても出来事を失わず、一時の失敗はやり直し、直らない失敗はすぐ諦めて出す", async () => {
  for (const [name, stop] of [["担当のワークフローが無効", { workflow: "disabled_manually" }], ["利用の上限で止まった直後",
    { last: [{ id: 5, conclusion: "failure", updated_at: new Date().toISOString() }], steps: [{ name: config.quotaStep, conclusion: "failure" }] }]]) {
    const off = world([{ n: 1, status: "未着手" }], stop);
    await off.send(ev.schedule());
    assert.deepEqual([off.titles(), off.updates.map((u) => u.status)], [[], ["AT_RISK"]], name);
  }
  const w = world([{ n: 1, status: "未着手", body: "- [x] 作る\n" }, { n: 2, status: "未着手", body: "- [x] 作る\n" }]);
  w.fail = Object.assign(new Error("GitHub が 502"), { transient: true });
  assert.ok((await w.send(ev.comment(1))) > Date.now(), "一時の失敗は、間をあけて起こす時刻を返す");
  w.fail = null;
  assert.ok((await w.send(ev.comment(2))) > Date.now(), "やり直しを待つ出来事がある間は、その時刻を返す");
  assert.deepEqual([w.at(1).status, w.at(2).status], ["未着手", "完了"], "待っている出来事があっても、後ろの出来事は先に進む");
  assert.equal(await w.inbox.drain(config.retries, Date.now() + 3600e3), null);
  assert.equal(w.at(1).status, "完了", "やり直しで処理した");
  w.fail = new Error("GitHub が 404");
  assert.equal(await w.send(ev.comment(1)), null, "やり直しても直らない失敗は、すぐ諦める");
  w.fail = null;
  await w.send(ev.schedule());
  assert.deepEqual([w.updates.at(-1).status, w.updates.at(-1).body.includes("404")], ["OFF_TRACK", true]);
  await w.send(ev.schedule());
  assert.equal(w.updates.at(-1).status, "ON_TRACK", "G8 出したら消し、戻ったら On track を書く");
});

test("tasks#307・K3・G4・G7: 本文の印の間・形に合わない問い・ボードの移動・着手可能日時の形", async () => {
  const w = world([{ n: 1, status: "未着手", body: "<!-- flow-gate -->\nメモ\n<!-- /flow-gate -->\n\n- [ ] 作る\n" },
    { n: 2, status: "回答待ち", comments: ["## 問い（判断）\n形に合わない"] }, { n: 3, status: "未着手", start: "来週" }]);
  await w.send(ev.issue(1, "edited"));
  assert.deepEqual([w.at(1).body.startsWith("メモ\n"), w.at(1).comments.length], [true, 1], "G3 印の間の見知らぬ行は、消さずに印の外の先頭へ出してコメントで知らせる");
  await w.send(ev.comment(2, config.claude));
  assert.match(head(w.at(2)), /形に合わないので/);
  await w.send(ev.issue(3, "edited"));
  assert.deepEqual([/着手可能日時「来週」/.test(head(w.at(3))), w.titles().includes("#3 作る")], [true, false], "G7 形の合わない着手可能日時は知らせ、まだ先と読んで振り出さない");
  w.at(1).status = "完了";
  await w.send(ev.move(1));
  const told = w.at(1).comments.at(-1);
  assert.deepEqual([w.at(1).state, [`「${w.at(1).status}」`, "保留", "完了"].every((t) => told.includes(t))], ["OPEN", true], "G4 戻した先と、ユーザーが直接決められるのは保留と完了だけであることを知らせる");
});

// 回答フォームは App の名義で読み、答えはユーザーの名義（FORM_TOKEN）で書く。GitHub への要求は world へつなぐ。
const key = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign"]);
const env = { APP_ID: 1, APP_KEY: Buffer.from(await crypto.subtle.exportKey("pkcs8", key.privateKey)).toString("base64"), FORM_TOKEN: "user" };
function connect(w) {
  globalThis.fetch = async (url, init = {}) => {
    const path = String(url).replace("https://api.github.com", "");
    const body = init.body ? JSON.parse(init.body) : undefined;
    const reply = (x, type = "application/json") => new Response(x == null ? null : type === "application/json" ? JSON.stringify(x) : x, { status: x == null ? 204 : 200, headers: { "content-type": type } });
    if (path.startsWith("/app/installations/")) return reply({ token: "app", expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/graphql") return reply({ data: await w.gh.gql(body.query, body.variables) });
    if (path === "/markdown") return reply(`<p>${body.text}</p>`, "text/html");
    return reply(await w.gh.rest(init.method, path, body));
  };
}
const url = (n) => `${config.urls.form}/answer?issue=${n}`;
const open = (n) => answerForm(new Request(url(n)), env, config);
// ブラウザと同じく、開いたページの隠しの欄（問いの文・確かめの項目）と、選んだ値を送る。
async function answer(n, picks) {
  const html = await (await open(n)).text();
  const form = new FormData();
  for (const [, name, value] of html.matchAll(/<input type="hidden" name="(\w+)" value="([^"]*)">/g)) form.set(name, value.replace(/&#(\d+);/g, (_, c) => String.fromCharCode(c)));
  for (const [k, v] of Object.entries(picks)) (form.delete(k), [v].flat().forEach((x) => form.append(k, x)));
  return (await answerForm(new Request(url(n), { method: "POST", body: form }), env, config)).json();
}

test("回答フォーム（R10〜R12・決め2・合意したモック）: 種類ごとに要るものだけを出し、次のステータスは出さない。送った答えでゲートが決め直す", async () => {
  const w = world([{ n: 1, status: "CI待ち", body: CONFIRM, pr: { state: "MERGED", merged: true, mergeChecks: "SUCCESS", sha: "m1" } },
    { n: 2, author: config.claude, type: "要望", board: null }, { n: 3, status: "未着手" }, { n: 4, status: "回答待ち", comments: [QUESTION] },
    { n: 5, status: "回答待ち", comments: ["### 作る担当の終わり\n担当の最後の発言",ASKED("イレギュラー")] }]);
  connect(w);
  await w.send(ev.ci(config.base, "m1")); // 確かめの問い
  await w.send(ev.issue(2, "opened", config.claude)); // 採否の問い
  const check = await (await open(1)).text();
  for (const text of ["ユーザーが確かめる: 見た目", "問題なし", "問題あり", "問題の内容", "確認", "戻る", "送信"]) assert.ok(check.includes(text), `確かめ: ${text}`);
  assert.ok(!check.includes("次のステータス"));
  const adopt = await (await open(2)).text();
  for (const text of ["着手する", "保留する", "見送る"]) assert.ok(adopt.includes(text), `採否: ${text}`);
  assert.ok((await (await open(4)).text()).includes("該当なし（補足に記入）"), "判断: 案と、該当なし（補足に記入）");
  const irregular = await (await open(5)).text();
  assert.ok(irregular.indexOf("担当の最後の発言") < irregular.indexOf("判断材料"), "イレギュラー: 何が起きたか（担当の終わり）を判断材料より上に出す");
  for (const text of ["やり直す", "保留する", "見送る"]) assert.ok(irregular.includes(text), `イレギュラー: ${text}`);
  assert.equal((await open(3)).status, 404, "答えていない問いが無い");
  assert.match((await answer(1, { question: "前の問い" })).error, /問いが新しくなっています/);
  await answer(1, { ok0: "問題あり", note0: "崩れる" });
  await w.send(ev.comment(1));
  assert.match(w.at(1).body, /- \[ \] 直す: 崩れる/, "決め2 問題ありの項目は直す行として条件に足す");
  assert.deepEqual([w.at(1).state, w.at(1).status], ["OPEN", "進行中"], "決め2 未着手にして作る担当へ（完成にしない）");
  await answer(2, { choice: "見送る", label: ["急ぎ"] });
  await w.send(ev.comment(2));
  assert.deepEqual([w.at(2).state, w.at(2).reason, w.at(2).labels], ["CLOSED", "NOT_PLANNED", ["急ぎ"]], "採否の見送るで閉じる。ラベルの付け外しも送る");
});

// テスト用の設定と GitHub。設定は本物（flow.config.json）を読まず、性質だけを表す架空の値で与える（本物のステータスの名前を
// 変えても、テストの意味は変わらない）。GitHub は網（fetch）だけを差し替え、置き場の issue・2つのボード・コードのリポジトリの
// 担当の実行・PR・チェックを持って、書き込みを記録する。
export const config = {
  repository: "o/tasks",
  project: { owner: "o", number: 1, statusField: "状態", priorityField: "重さ", urgentLabel: "急", startField: "開始日", unsetPriority: "並" },
  dialog: { project: 7, type: "対話" },
  gate: "gate[bot]",
  urls: { gate: "https://gate.example", form: "https://form.example" },
  people: { u: { id: 1, node: "N_U" }, c: { id: 2, node: "N_C" } },
  user: "u",
  claude: "c",
  status: { todo: "前", working: "中", ci: "試", ready: "待検", review: "検", waiting: "答え待ち", hold: "置き", done: "済" },
  todoTypes: ["保"],
  userCheck: "人が見る",
  questionTemplate: "## 問い（判断）\n<問い>\n\n### 案\n- <案>\n\n<details><summary>判断材料</summary>\n\n**約束**: <約束>\n**案ごと**: <案ごと>\n**推奨**: <推奨>\n</details>",
  code: { repository: "o/code", branchPrefix: "work/t-", base: "main", mutation: { check: "変異", title: "気づかない" } },
  coordinator: { workflow: "w.yml", slots: { 作る: 2, 確かめる: 1 } },
};

const STATUSES = Object.values(config.status);
const LOGIN = Object.fromEntries(Object.entries(config.people).map(([k, p]) => [p.node, k]));
const AS = { "Bearer form-token": config.user, "Bearer bot-token": config.claude };
const TYPES = ["保", "要", config.dialog.type].map((name) => ({ id: `T:${name}`, name }));
const BOARDS = { A: { id: "PVT", number: config.project.number }, D: { id: "PVT_D", number: config.dialog.project } };

// issues: issue の並び。issue は { number, author（login）, type, status, body, labels, assignees, fields, comments（{ author, body }）,
// lastClose, blockedBy（前提の状態の並び）, parent（番号）, boards（"A"＝Actions のボード・"D"＝対話作業のボード）, typeEvents（新しいものが後。
// { prev, type } で、prev が無ければ付いた・type が無ければ外れた） }。
// runs: 担当の実行（{ id, number, kind, status（既定 in_progress）, conclusion }）。branchRuns: 作業ブランチの CI の実行（{ branch, status }）。
// prs: 作業ブランチの PR（{ number, branch, draft, state（OPEN・MERGED・CLOSED）, head, convertedAt, commits（古い順の sha） }）。
// checks: sha → チェック（{ name, status（既定 completed）, conclusion（既定 success）, completedAt, notes（注記の題名と文の並び） }）。
// required: 必須のチェックの名前。
export function fakeGitHub({ issues = [], runs = [], branchRuns = [], prs = [], checks = {}, required = ["必須"], labels = [config.project.urgentLabel, "札"], tasks = null } = {}) {
  const blank = { state: "OPEN", body: "本文", labels: [], assignees: [], fields: {}, comments: [], lastClose: [], blockedBy: [], boards: ["A"], typeEvents: [] };
  const s = { issues: issues.map((i) => ({ ...blank, ...i })), runs, branchRuns, prs, checks, writes: [], cancels: [], readies: [], dispatches: [], created: [] };
  s.issue = s.issues[0];
  const byNumber = (n) => s.issues.find((i) => i.number === Number(n));
  const byId = (id) => s.issues.find((i) => `I${i.number}` === id);
  const node = (i) => ({
    id: `I${i.number}`, number: i.number, title: "題名", body: i.body, url: `https://github.com/${config.repository}/issues/${i.number}`, state: i.state,
    author: { databaseId: config.people[i.author ?? config.user]?.id }, issueType: i.type ? { id: `T:${i.type}`, name: i.type } : null,
    parent: i.parent ? { number: i.parent } : null,
    assignees: { nodes: i.assignees.map((login) => ({ id: config.people[login].node, login })) }, labels: { nodes: i.labels.map((name) => ({ name })) },
    lastClose: { nodes: i.lastClose }, repository: { id: "R", nameWithOwner: config.repository }, blockedBy: { nodes: i.blockedBy.map((state, k) => ({ number: k, state })) },
    comments: { nodes: i.comments.map((c, k) => ({ author: { login: c.author }, createdAt: "2026-10-04T00:00:00Z", url: `c${k}`, body: c.body, bodyHTML: `<p>描いた: ${c.body}</p>` })) },
    projectItems: { nodes: i.boards.map((b) => ({ id: `PVTI_${b}${i.number}`, project: BOARDS[b], fieldValues: { nodes: b === "D" ? [] : [
      ...(i.status ? [{ name: i.status, field: { name: config.project.statusField } }] : []),
      ...Object.entries(i.fields).map(([name, v]) => (name === config.project.startField ? { text: v, field: { name } } : { name: v, field: { name } }))] } })) },
  });
  const apply = (name, input, as) => {
    s.writes.push({ op: name, as, ...input });
    const i = byId(input.id ?? input.issueId ?? input.subjectId ?? input.contentId) ?? s.issues.find((x) => input.itemId?.endsWith(`${x.number}`));
    if (name === "updateProjectV2ItemFieldValue") {
      const v = input.value.singleSelectOptionId ?? input.value.text;
      if (input.fieldId === "F") i.status = v.slice(2);
      else i.fields = { ...i.fields, [input.fieldId]: input.value.singleSelectOptionId ? v.split(":")[1] : v };
    }
    if (name === "addComment") i.comments.push({ author: as, body: input.body });
    if (name === "updateIssue") {
      if (input.assigneeIds) i.assignees = input.assigneeIds.map((id) => LOGIN[id]);
      if ("body" in input) i.body = input.body;
      if (input.stateInput) Object.assign(i, { state: "CLOSED", lastClose: [{ stateReason: input.stateInput.stateReason }] });
      if ("issueTypeId" in input) i.type = input.issueTypeId?.slice(2) ?? null;
    }
    if (name === "reopenIssue") i.state = "OPEN";
    if (name === "addProjectV2ItemById") i.boards = [...new Set([...i.boards, input.projectId === "PVT" ? "A" : "D"])];
    if (name === "markPullRequestReadyForReview") s.readies.push(input.pullRequestId);
    if (name === "removeLabelsFromLabelable") i.labels = i.labels.filter((l) => !input.labelIds.includes(`L:${l}`));
    return {};
  };
  const graphql = ({ query, variables: v }, as) => {
    if (query.startsWith("query Task")) {
      const i = v.id ? byId(v.id) : byNumber(v.k);
      return { data: { organization: { projectV2: { id: "PVT", fields: { nodes: [
        { id: "F", name: config.project.statusField, options: STATUSES.map((name) => ({ id: `S:${name}`, name })) },
        { id: config.project.priorityField, name: config.project.priorityField, options: ["上", "並", "下"].map((o) => ({ id: `${config.project.priorityField}:${o}`, name: o })) },
        { id: config.project.startField, name: config.project.startField, dataType: "TEXT" }] } } },
        repository: { labels: { nodes: labels.map((name) => ({ id: `L:${name}`, name })) }, issue: i && node(i) }, node: i && node(i) } };
    }
    if (query.startsWith("query Board")) return { data: { organization: { projectV2: { id: BOARDS[v.n === config.dialog.project ? "D" : "A"].id } } } };
    if (query.startsWith("query Types")) return { data: { organization: { issueTypes: { nodes: TYPES } } } };
    if (query.startsWith("query TypeEvents")) {
      const i = byId(v.id);
      return { data: { node: { timelineItems: { nodes: i.typeEvents.map((e) => (e.prev && e.type ? { __typename: "IssueTypeChangedEvent", prevIssueType: { name: e.prev }, issueType: { name: e.type } }
        : e.type ? { __typename: "IssueTypeAddedEvent", issueType: { name: e.type } } : { __typename: "IssueTypeRemovedEvent", issueType: { name: e.prev } })) } } } };
    }
    if (query.startsWith("query Pulls")) {
      return { data: { repository: { pullRequests: { nodes: s.prs.filter((p) => p.branch === v.b).map((p) => ({ id: `PR${p.number}`, number: p.number, isDraft: Boolean(p.draft), state: p.state ?? "OPEN",
        headRefOid: p.head, timelineItems: { nodes: p.convertedAt ? [{ createdAt: p.convertedAt }] : [] }, commits: { nodes: (p.commits ?? [p.head]).map((oid) => ({ commit: { oid } })) } })) } } } };
    }
    if (query.startsWith("query Items")) {
      const list = (tasks ?? s.issues).filter((t) => (t.boards ?? ["A"]).includes("A") && (t.state ?? "OPEN") === "OPEN");
      return { data: { organization: { projectV2: { field: { options: ["上", "並", "下"].map((name) => ({ name })) }, items: { pageInfo: { hasNextPage: false }, nodes: list.map((t) => ({
        status: t.status ? { name: t.status } : null, priority: t.priority ? { name: t.priority } : null, size: null, start: t.fields?.[config.project.startField] ? { text: t.fields[config.project.startField] } : null,
        content: { number: t.number, labels: { nodes: (t.labels ?? []).map((name) => ({ name })) }, blockedBy: { nodes: (t.blockedBy ?? []).map((state) => ({ state })) } } })) } } } } };
    }
    if (query.startsWith("mutation C")) {
      const number = 100 + s.created.length;
      s.created.push({ number, ...v.i });
      s.issues.push({ ...blank, number, author: as, type: v.i.issueTypeId?.slice(2), parent: byId(v.i.parentIssueId)?.number, boards: [], status: null, body: v.i.body });
      return { data: { createIssue: { issue: { id: `I${number}`, number, url: `u${number}` } } } };
    }
    const out = {};
    for (const [, key, name] of query.matchAll(/(m\d+): (\w+)\(input/g)) out[key] = apply(name, v[key], as) && (name === "addProjectV2ItemById" ? { item: { id: "PVTI" } } : {});
    return { data: out };
  };
  const runJson = (r) => ({ id: r.id, display_title: `#${r.number} ${r.kind}`, status: r.status ?? "in_progress", conclusion: r.conclusion ?? null,
    html_url: `https://x/actions/runs/${r.id}`, created_at: `2026-10-04T00:00:${String(r.id).padStart(2, "0")}Z` });
  globalThis.fetch = async (url, init = {}) => {
    const { pathname: path, searchParams: q } = new URL(url);
    const body = init.body ? JSON.parse(init.body) : null;
    const as = AS[init.headers.authorization] ?? "gate";
    const json = (b, status = 200) => new Response(JSON.stringify(b), { status });
    if (path.endsWith("/access_tokens")) return json({ token: "app-token", expires_at: "2099-01-01T00:00:00Z" });
    if (path.endsWith("/installation")) return json({ id: path.includes(config.code.repository) ? 2 : 1 });
    if (path === "/graphql") return json(graphql(body, as));
    if (path === "/markdown") return new Response(`<p>描いた: ${body.text}</p>`);
    const code = `/repos/${config.code.repository}`;
    if (path === `${code}/actions/workflows/${config.coordinator.workflow}/runs`) {
      const st = q.get("status");
      return json({ workflow_runs: s.runs.map(runJson).filter((r) => !st || r.status === st || (st === "completed" && r.status === "completed")) });
    }
    if (path === `${code}/actions/runs`) return json({ workflow_runs: s.branchRuns.filter((r) => r.branch === q.get("branch")).map((r, k) => ({ id: k, status: r.status ?? "completed" })) });
    const cancel = /\/actions\/runs\/(\d+)\/cancel$/.exec(path);
    if (cancel && init.method === "POST") return s.cancels.push(Number(cancel[1])), json({}, 202);
    if (path === `${code}/rules/branches/${config.code.base}`) return json([{ type: "required_status_checks", parameters: { required_status_checks: required.map((context) => ({ context })) } }]);
    const commit = /\/commits\/(\w+)\/check-runs$/.exec(path);
    if (commit) return json({ check_runs: (s.checks[commit[1]] ?? []).map((c, k) => ({ id: `${commit[1]}-${k}`, name: c.name, status: c.status ?? "completed",
      conclusion: (c.status ?? "completed") === "completed" ? (c.conclusion ?? "success") : null, completed_at: c.completedAt ?? "2026-10-04T01:00:00Z" })) });
    const notes = /\/check-runs\/(\w+)-(\d+)\/annotations$/.exec(path);
    if (notes) return json((s.checks[notes[1]][Number(notes[2])].notes ?? []).map(([title, message]) => ({ title, message, path: "a.py" })));
    if (path === `/repos/${config.repository}/dispatches` && init.method === "POST") return s.dispatches.push(body.client_payload.number), new Response(null, { status: 204 });
    const comment = /\/issues\/(\d+)\/comments$/.exec(path);
    if (comment && init.method === "POST") return json(apply("addComment", { id: `I${comment[1]}`, body: body.body }, as));
    throw new Error(`テストの GitHub が知らない呼び出し: ${init.method} ${path}`);
  };
  return s;
}

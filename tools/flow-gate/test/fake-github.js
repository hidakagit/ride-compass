// テスト用の GitHub。ゲートの網の外側（fetch）だけを差し替え、書き込みと呼び出しの回数を記録する。
import config from "../flow.config.json" with { type: "json" };

const OPTIONS = Object.fromEntries(config.statuses.map((s, i) => [s, `opt${i}`]));
const NAMES = Object.fromEntries(Object.entries(OPTIONS).map(([k, v]) => [v, k]));
// Status のほかの単一選択の欄（Project に足してあるもの）。選択肢の id は「欄の名前:選択肢」。
const FIELDS = { [config.project.priorityField]: ["高", "中", "低"], [config.project.sizeField]: ["S", "M", "L"] };
const BY_NODE = Object.fromEntries(Object.entries(config.people).map(([k, p]) => [p.node, k]));

// code はコードのリポジトリの状態（Pull Request の一覧）。
// parent を渡すと、issue をその子にする（親の子は、parent.siblings の状態と issue の今の状態）。親の id は I_P。
// markdown を false にすると、Markdown を描く呼び出しが失敗する。fail を渡すと、タスクを読む呼び出しがその文で失敗する。
// updates は Project の状況の更新（新しいものが先。{ id, status, body, by, updatedAt? }）。トークン bot-token は hidakagit-bot の名義。
export function fakeGitHub({ issue, parent, labels = [config.project.urgentLabel, "規模S", config.confirmLabel], code = { prs: [] }, markdown = true, fail, updates = [] }) {
  const blank = { blockedBy: [], subIssues: [], assignees: [], labels: [], lastClose: [], state: "OPEN", fields: {} };
  const state = {
    issue: { ...blank, ...issue },
    parent: parent && { ...blank, siblings: [], ...parent },
    writes: [],
    requests: [],
    calls: 0,
    code,
    updates,
  };
  const byId = (id) => (id === "I_P" || id === "PVTI_P" ? state.parent : state.issue);
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
  const node = (i) => {
    const main = i === state.issue;
    return {
      id: main ? "I_1" : "I_P", number: i.number, title: "題名", body: i.body ?? "本文", url: `https://github.com/${config.repository}/issues/${i.number}`,
      state: i.state, author: { databaseId: i.authorId },
      parent: main && state.parent ? { number: state.parent.number } : (i.parent ?? null),
      assignees: { nodes: i.assignees.map((login) => ({ id: config.people[login]?.node, login })) },
      labels: { nodes: i.labels.map((name) => ({ name })) }, blockedBy: { nodes: i.blockedBy },
      subIssues: { nodes: main ? i.subIssues : [...i.siblings, { state: state.issue.state }] },
      lastClose: { nodes: i.lastClose }, repository: { nameWithOwner: config.repository },
      projectItems: { nodes: [{ id: main ? "PVTI_1" : "PVTI_P", project: { id: "PVT_1" }, fieldValues: { nodes: [
        ...(i.status ? [{ name: i.status, field: { name: config.project.statusField } }] : []),
        ...Object.entries(i.fields).map(([name, value]) => ({ name: value, field: { name } })),
      ] } }] },
    };
  };
  const apply = (name, input, as) => {
    state.writes.push({ op: name, as, ...input });
    if (name === "createProjectV2StatusUpdate") state.updates.unshift({ id: `SU_${state.updates.length + 1}`, status: input.status, body: input.body, by: as });
    if (name === "updateProjectV2StatusUpdate") Object.assign(state.updates.find((u) => u.id === input.statusUpdateId), { status: input.status, body: input.body });
    if (name.endsWith("StatusUpdate")) return { clientMutationId: null };
    const i = byId(input.id ?? input.itemId ?? input.subjectId ?? input.issueId);
    if (name === "updateProjectV2ItemFieldValue" && input.fieldId === "F_1") i.status = NAMES[input.value.singleSelectOptionId];
    else if (name === "updateProjectV2ItemFieldValue") {
      const [field, value] = input.value.singleSelectOptionId.split(":");
      i.fields = { ...i.fields, [field]: value };
    }
    if (name === "clearProjectV2ItemFieldValue") i.status = null;
    if (name === "updateIssue" && input.assigneeIds) i.assignees = input.assigneeIds.map((id) => BY_NODE[id]);
    if (name === "updateIssue" && "body" in input) i.body = input.body;
    if (name === "updateIssue" && input.labelIds) i.labels = input.labelIds.map((id) => id.slice(2));
    if (name === "updateIssue" && input.stateInput) i.state = input.stateInput.value;
    if (name === "reopenIssue") i.state = "OPEN";
    return { clientMutationId: null };
  };
  const graphql = ({ query, variables }, as) => {
    if (query.startsWith("query Open")) return { repository: { issues: { pageInfo: { hasNextPage: false }, nodes: [{ number: state.issue.number }] } } };
    if (query.startsWith("query Updates")) {
      const nodes = state.updates.slice(0, variables.k).map(({ by, ...u }) => ({ createdAt: "t", updatedAt: "t", ...u, creator: { login: by } }));
      return { organization: { projectV2: { id: "PVT_1", statusUpdates: { nodes } } } };
    }
    if (query.startsWith("query Task") && state.requests.push("読む")) {
      const i = state.parent && (variables.id === "I_P" || variables.k === state.parent.number) ? state.parent : state.issue;
      return {
        organization: { projectV2: { id: "PVT_1", fields: { nodes: [
          { id: "F_1", name: config.project.statusField, options: Object.entries(OPTIONS).map(([name, id]) => ({ id, name })) },
          ...Object.entries(FIELDS).map(([field, options]) => ({ id: `F_${field}`, name: field, options: options.map((o) => ({ id: `${field}:${o}`, name: o })) })),
          { id: "F_title", name: "Title" },
        ] } } },
        repository: { labels: { nodes: labels.map((name) => ({ id: `L:${name}`, name })) }, issue: node(i) },
        node: node(i),
      };
    }
    const data = {};
    const ops = [...query.matchAll(/(m\d+): (\w+)\(input: \$m\d+\)/g)];
    state.requests.push(ops.map(([, , name]) => name).join("+"));
    for (const [, key, name] of ops) data[key] = apply(name, variables[key], as);
    return data;
  };
  globalThis.fetch = async (url, init = {}) => {
    state.calls++;
    const path = new URL(url).pathname;
    const body = init.body ? JSON.parse(init.body) : null;
    const as = { "Bearer form-token": "hidakagit", "Bearer bot-token": "hidakagit-bot" }[init.headers.authorization] ?? "gate";
    if (path.endsWith("/access_tokens")) return json({ token: "app-token" });
    if (path === "/graphql" && fail && body.query.startsWith("query Task")) return json({ errors: [{ message: fail }] });
    if (path === "/graphql") return json({ data: graphql(body, as) });
    if (path === "/markdown") return markdown ? new Response(`<p>描いた: ${body.text}</p>`) : new Response("失敗", { status: 500 });
    const repo = `/repos/${config.code.repository}`;
    if (path === `${repo}/pulls`) return json(state.code.prs.filter((p) => `${config.code.repository.split("/")[0]}:${p.head.ref}` === new URL(url).searchParams.get("head")));
    throw new Error(`テストの GitHub が知らない呼び出し: ${init.method} ${path}`);
  };
  return state;
}

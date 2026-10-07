// テスト用の設定と GitHub。設定は本物（flow.config.json）を読まず、性質だけを表す架空の値で与える（本物の遷移の表やステータスの名前を
// 変えても、テストの意味は変わらない）。GitHub は網（fetch）だけを差し替え、1件の issue と Project・コメント・状況の更新を持って、
// 書き込みを記録する。
export const config = {
  repository: "o/tasks",
  project: { owner: "o", number: 1, statusField: "状態", priorityField: "重さ", urgentLabel: "急", sizeField: "大きさ", startField: "開始日", unsetPriority: "並" },
  gate: "gate[bot]",
  urls: { gate: "https://gate.example", form: "https://form.example" },
  installation: 1,
  people: { u: { id: 1, node: "N_U" }, c: { id: 2, node: "N_C" } },
  user: "u",
  claude: "c",
  statuses: ["答え待ち", "置き", "前", "中", "検", "済"],
  owner: { 答え待ち: "u", 置き: "u", 前: "c", 中: "c", 検: "c" },
  done: "済", waiting: "答え待ち", hold: "置き", todo: "前", working: "中", review: "検",
  question: "どうする？",
  transitions: { 答え待ち: ["前", "置き", "済"], 置き: ["前", "答え待ち", "済"], 前: ["中", "答え待ち", "置き", "済"], 中: ["検", "前", "置き", "答え待ち", "済"], 検: ["済", "前", "答え待ち"], 済: [] },
  code: { repository: "o/code", branchPrefix: "work/t-", base: "main", gather: "まとめ" },
  coordinator: { workflow: "w.yml", slots: { 作る: 2, 確かめる: 1 }, devLabel: "機", recent: 4, recordsSince: "2026-10-01T00:00:00Z", backendVariable: "B", backupMaxHours: 24 },
};

const OPTIONS = Object.fromEntries(config.statuses.map((s) => [s, `S:${s}`]));
const FIELDS = { [config.project.priorityField]: ["上", "並", "下"], [config.project.sizeField]: ["S", "M", "L"] };
const LOGIN = Object.fromEntries(Object.entries(config.people).map(([k, p]) => [p.node, k]));
const AS = { "Bearer form-token": config.user, "Bearer bot-token": config.claude };

// issue: { number, author（login）, status, body, labels, assignees（login）, fields, comments（{ author, body }）, parent, lastClose }
// parent を渡すと issue をその子にし、親の優先度は parent.fields から読む。records は番号 → 記録の並び（コメント { by, at, body } か
// 閉じ { closed: at }）で、見回りが issue ごとに読むもの（読んだ番号を read に残す）。
export function fakeGitHub({ issue, parent, labels = [config.project.urgentLabel, "札"], updates = [], records = {} }) {
  const blank = { state: "OPEN", body: "本文", labels: [], assignees: [], fields: {}, comments: [], lastClose: [] };
  const s = { issue: { ...blank, ...issue }, parent: parent && { ...blank, ...parent }, writes: [], updates, read: [] };
  const node = (i) => ({
    id: i === s.parent ? "I_P" : "I_1", number: i.number, title: "題名", body: i.body, url: `https://github.com/${config.repository}/issues/${i.number}`, state: i.state,
    author: { databaseId: config.people[i.author ?? config.user]?.id }, parent: i === s.issue && s.parent ? { number: s.parent.number } : null,
    assignees: { nodes: i.assignees.map((login) => ({ id: config.people[login].node, login })) }, labels: { nodes: i.labels.map((name) => ({ name })) },
    lastClose: { nodes: i.lastClose }, repository: { nameWithOwner: config.repository },
    comments: { nodes: i.comments.map((c, k) => ({ author: { login: c.author }, createdAt: "2026-10-04T00:00:00Z", url: `c${k}`, body: c.body, bodyHTML: `<p>描いた: ${c.body}</p>` })) },
    projectItems: { nodes: [{ id: "PVTI", project: { id: "PVT" }, fieldValues: { nodes: [
      { name: i.status, field: { name: config.project.statusField } },
      ...Object.entries(i.fields).map(([name, v]) => (name === config.project.startField ? { date: v, field: { name } } : { name: v, field: { name } }))] } }] },
  });
  const apply = (name, input, as) => {
    s.writes.push({ op: name, as, ...input });
    const i = input.id === "I_P" ? s.parent : s.issue;
    if (name === "updateProjectV2ItemFieldValue") {
      const v = input.value.singleSelectOptionId ?? input.value.date;
      if (input.fieldId === "F") i.status = v.slice(2);
      else i.fields = { ...i.fields, [input.fieldId]: v.includes(":") ? v.split(":")[1] : v };
    }
    if (name === "addComment") i.comments.push({ author: as, body: input.body });
    if (name === "updateIssue") {
      if (input.assigneeIds) i.assignees = input.assigneeIds.map((id) => LOGIN[id]);
      if (input.labelIds) i.labels = input.labelIds.map((id) => id.slice(2));
      if ("body" in input) i.body = input.body;
      if (input.stateInput) i.state = "CLOSED";
    }
    if (name === "reopenIssue") i.state = "OPEN";
    if (name === "createProjectV2StatusUpdate") s.updates.unshift({ id: `U${s.updates.length}`, status: input.status, body: input.body, by: as });
    if (name === "updateProjectV2StatusUpdate") Object.assign(s.updates.find((u) => u.id === input.statusUpdateId), { status: input.status, body: input.body });
  };
  const graphql = ({ query, variables: v }, as) => {
    if (query.startsWith("query Task")) {
      const i = s.parent && (v.k === s.parent.number || v.id === "I_P") ? s.parent : s.issue;
      return { data: { organization: { projectV2: { id: "PVT", fields: { nodes: [
        { id: "F", name: config.project.statusField, options: Object.entries(OPTIONS).map(([name, id]) => ({ id, name })) },
        ...Object.entries(FIELDS).map(([f, os]) => ({ id: f, name: f, options: os.map((o) => ({ id: `${f}:${o}`, name: o })) })),
        { id: config.project.startField, name: config.project.startField, dataType: "DATE" }] } } },
        repository: { labels: { nodes: labels.map((name) => ({ id: `L:${name}`, name })) }, issue: node(i) }, node: node(i) } };
    }
    if (query.startsWith("query Open")) return { data: { repository: { issues: { pageInfo: { hasNextPage: false }, nodes: [{ number: s.issue.number }] } } } };
    // GraphQL は App の名義を [bot] を付けずに返す。
    if (query.startsWith("query Records")) {
      const numbers = [...query.matchAll(/i(\d+): issue/g)].map(([, k]) => Number(k));
      s.read.push(...numbers);
      return { data: { repository: Object.fromEntries(numbers.map((k) => [`i${k}`, { timelineItems: { nodes: (records[k] ?? []).map((r) =>
        (r.closed ? { __typename: "ClosedEvent", createdAt: r.closed } : { __typename: "IssueComment", createdAt: r.at, body: r.body, author: { login: r.by.replace(/\[bot\]$/, "") } })) } }])) } };
    }
    if (query.startsWith("query Updates"))
      return { data: { organization: { projectV2: { id: "PVT", statusUpdates: { nodes: s.updates.slice(0, 1).map(({ by, ...u }) => ({ ...u, creator: { login: by } })) } } } } };
    for (const [, key, name] of query.matchAll(/(m\d+): (\w+)\(input/g)) apply(name, v[key], as);
    return { data: {} };
  };
  globalThis.fetch = async (url, init = {}) => {
    const path = new URL(url).pathname;
    const body = init.body ? JSON.parse(init.body) : null;
    const as = AS[init.headers.authorization] ?? "gate";
    const json = (b, status = 200) => new Response(JSON.stringify(b), { status });
    if (path.endsWith("/access_tokens")) return json({ token: "app-token", expires_at: "2099-01-01T00:00:00Z" });
    if (path === "/graphql") return json(graphql(body, as));
    if (path === "/markdown") return new Response(`<p>描いた: ${body.text}</p>`);
    throw new Error(`テストの GitHub が知らない呼び出し: ${init.method} ${path}`);
  };
  return s;
}

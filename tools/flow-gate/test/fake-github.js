// テスト用の GitHub。網（fetch）だけを差し替え、1件の issue と Project・コメント・状況の更新を持って、書き込みを記録する。
import config from "../flow.config.json" with { type: "json" };

const OPTIONS = Object.fromEntries(config.statuses.map((s) => [s, `S:${s}`]));
const FIELDS = { [config.project.priorityField]: ["高", "中", "低"], [config.project.sizeField]: ["S", "M", "L"] };
const LOGIN = Object.fromEntries(Object.entries(config.people).map(([k, p]) => [p.node, k]));
const AS = { "Bearer form-token": config.user, "Bearer bot-token": config.claude };

// issue: { number, author（login）, status, body, labels, assignees（login）, fields, comments（{ author, body }）, parent, lastClose }
// parent を渡すと issue をその子にし、親の優先度は parent.fields から読む。
export function fakeGitHub({ issue, parent, labels = [config.project.urgentLabel, "規模S"], updates = [] }) {
  const blank = { state: "OPEN", body: "本文", labels: [], assignees: [], fields: {}, comments: [], lastClose: [], statusAt: "2026-10-03T00:00:00Z" };
  const s = { issue: { ...blank, ...issue }, parent: parent && { ...blank, ...parent }, writes: [], updates };
  const node = (i) => ({
    id: i === s.parent ? "I_P" : "I_1", number: i.number, title: "題名", body: i.body, url: `https://github.com/${config.repository}/issues/${i.number}`, state: i.state,
    author: { databaseId: config.people[i.author ?? config.user]?.id }, parent: i === s.issue && s.parent ? { number: s.parent.number } : null,
    assignees: { nodes: i.assignees.map((login) => ({ id: config.people[login].node, login })) }, labels: { nodes: i.labels.map((name) => ({ name })) },
    lastClose: { nodes: i.lastClose }, repository: { nameWithOwner: config.repository },
    comments: { nodes: i.comments.map((c, k) => ({ author: { login: c.author }, createdAt: "2026-10-04T00:00:00Z", url: `c${k}`, body: c.body, bodyHTML: `<p>描いた: ${c.body}</p>` })) },
    projectItems: { nodes: [{ id: "PVTI", project: { id: "PVT" }, fieldValues: { nodes: [
      { name: i.status, updatedAt: i.statusAt, field: { name: config.project.statusField } },
      ...Object.entries(i.fields).map(([name, v]) => (name === config.project.startField ? { date: v, field: { name } } : { name: v, field: { name } }))] } }] },
  });
  const apply = (name, input, as) => {
    s.writes.push({ op: name, as, ...input });
    const i = input.id === "I_P" ? s.parent : s.issue;
    if (name === "updateProjectV2ItemFieldValue") {
      const v = input.value.singleSelectOptionId ?? input.value.date;
      if (input.fieldId === "F") Object.assign(i, { status: v.slice(2), statusAt: new Date(Date.parse(i.statusAt) + 1000).toISOString() });
      else i.fields = { ...i.fields, [input.fieldId]: v.includes(":") ? v.split(":")[1] : v };
    }
    if (name === "clearProjectV2ItemFieldValue") delete i.fields[input.fieldId];
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
    const comments = `/repos/${config.repository}/issues/${s.issue.number}/comments`;
    const ids = () => s.issue.comments.map((c, k) => ({ id: k + 1, body: c.body, html_url: `c${k}` })).filter((c) => s.issue.comments[c.id - 1].body !== null);
    if (path === comments && init.method === "POST") return (apply("addComment", { subjectId: "I_1", body: body.body }, as), json(ids().at(-1), 201));
    if (path === comments) return json(ids());
    const gone = /\/issues\/comments\/(\d+)$/.exec(path);
    if (gone && init.method === "DELETE") return (s.issue.comments[gone[1] - 1].body = null, new Response(null, { status: 204 }));
    throw new Error(`テストの GitHub が知らない呼び出し: ${init.method} ${path}`);
  };
  return s;
}

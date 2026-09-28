// テスト用の GitHub。ゲートの網の外側（fetch）だけを差し替え、書き込みと呼び出しの回数を記録する。
import config from "../flow.config.json" with { type: "json" };

const OPTIONS = Object.fromEntries(config.statuses.map((s, i) => [s, `opt${i}`]));
const NAMES = Object.fromEntries(Object.entries(OPTIONS).map(([k, v]) => [v, k]));
// Status のほかの単一選択の欄（Project に足してあるもの）。選択肢の id は「欄の名前:選択肢」。
const FIELDS = { [config.project.priorityField]: ["高", "中", "低"], [config.project.sizeField]: ["S", "M", "L"] };
const BY_NODE = Object.fromEntries(Object.entries(config.people).map(([k, p]) => [p.node, k]));

// code はコードのリポジトリの状態（Pull Request の一覧・master の CI の実行）。
export function fakeGitHub({ issue, labels = [config.project.urgentLabel, "規模S", config.verify.label], code = { prs: [], runs: [] } }) {
  const repoLabels = [...labels, ...config.statuses.map((s) => `${config.statusLabelPrefix}${s}`)];
  const state = {
    issue: { comments: [], blockedBy: [], subIssues: [], assignees: [], labels: [], lastClose: [], state: "OPEN", fields: {}, ...issue },
    writes: [],
    requests: [],
    calls: 0,
    code,
  };
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
  const node = () => {
    const i = state.issue;
    return {
      id: "I_1", number: i.number, title: "題名", body: i.body ?? "本文", url: `https://github.com/${config.repository}/issues/${i.number}`,
      state: i.state, stateReason: null, author: { login: "x", databaseId: i.authorId }, parent: i.parent ?? null,
      assignees: { nodes: i.assignees.map((login) => ({ id: config.people[login]?.node, login })) },
      labels: { nodes: i.labels.map((name) => ({ name })) }, blockedBy: { nodes: i.blockedBy }, subIssues: { nodes: i.subIssues },
      comments: { nodes: i.comments.map((c, k) => ({ id: `C_${k}`, url: `u#${k}`, isMinimized: false, ...c })) },
      lastClose: { nodes: i.lastClose }, repository: { nameWithOwner: config.repository },
      projectItems: { nodes: [{ id: "PVTI_1", project: { id: "PVT_1" }, fieldValues: { nodes: [
        ...(i.status ? [{ name: i.status, field: { name: config.project.statusField } }] : []),
        ...Object.entries(i.fields).map(([name, value]) => ({ name: value, field: { name } })),
      ] } }] },
    };
  };
  const apply = (name, input, as) => {
    const i = state.issue;
    state.writes.push({ op: name, as, ...input });
    if (name === "updateProjectV2ItemFieldValue" && input.fieldId === "F_1") i.status = NAMES[input.value.singleSelectOptionId];
    else if (name === "updateProjectV2ItemFieldValue") {
      const [field, value] = input.value.singleSelectOptionId.split(":");
      i.fields = { ...i.fields, [field]: value };
    }
    if (name === "clearProjectV2ItemFieldValue") i.status = null;
    if (name === "addComment") {
      i.comments.push({ body: input.body, author: { login: as === "hidakagit" ? "hidakagit" : "ridecompass-gate" } });
      return { commentEdge: { node: { id: "C_new", url: "u#new" } } };
    }
    if (name === "updateIssue" && input.assigneeIds) i.assignees = input.assigneeIds.map((id) => BY_NODE[id]);
    if (name === "updateIssue" && "body" in input) i.body = input.body;
    if (name === "updateIssue" && input.labelIds) i.labels = input.labelIds.map((id) => id.slice(2));
    if (name === "updateIssue" && input.stateInput) i.state = input.stateInput.value;
    if (name === "addLabelsToLabelable") i.labels.push(...input.labelIds.map((id) => id.slice(2)));
    if (name === "removeLabelsFromLabelable") i.labels = i.labels.filter((l) => !input.labelIds.includes(`L:${l}`));
    if (name === "closeIssue" && input.issueId === "I_1") i.state = "CLOSED";
    if (name === "reopenIssue") i.state = "OPEN";
    return { clientMutationId: null };
  };
  const graphql = ({ query, variables }, as) => {
    if (query.startsWith("query Verifying")) {
      const on = state.issue.state === "OPEN" && `${config.statusLabelPrefix}${state.issue.status}` === variables.l;
      return { repository: { issues: { nodes: on ? [{ number: state.issue.number }] : [] } } };
    }
    if (query.startsWith("query Task") && state.requests.push("読む"))
      return {
        organization: { projectV2: { id: "PVT_1", fields: { nodes: [
          { id: "F_1", name: config.project.statusField, options: Object.entries(OPTIONS).map(([name, id]) => ({ id, name })) },
          ...Object.entries(FIELDS).map(([field, options]) => ({ id: `F_${field}`, name: field, options: options.map((o) => ({ id: `${field}:${o}`, name: o })) })),
          { id: "F_title", name: "Title" },
        ] } } },
        repository: { labels: { nodes: repoLabels.map((name) => ({ id: `L:${name}`, name })) }, issue: node() },
        node: node(),
      };
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
    const as = init.headers.authorization === "Bearer form-token" ? "hidakagit" : "gate";
    if (path.endsWith("/access_tokens")) return json({ token: "app-token" });
    if (path === "/graphql") return json({ data: graphql(body, as) });
    const repo = `/repos/${config.code.repository}`;
    if (path === `${repo}/pulls`) return json(state.code.prs.filter((p) => `${config.code.repository.split("/")[0]}:${p.head.ref}` === new URL(url).searchParams.get("head")));
    if (path === `${repo}/actions/runs`) return json({ workflow_runs: state.code.runs.filter((r) => r.head_sha === new URL(url).searchParams.get("head_sha")) });
    throw new Error(`テストの GitHub が知らない呼び出し: ${init.method} ${path}`);
  };
  return state;
}

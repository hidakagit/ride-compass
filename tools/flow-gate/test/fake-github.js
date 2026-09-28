// テスト用の GitHub。ゲートの網の外側（fetch）だけを差し替え、書き込みを記録する。
import config from "../flow.config.json" with { type: "json" };

const OPTIONS = Object.fromEntries(config.statuses.map((s, i) => [s, `opt${i}`]));
const NAMES = Object.fromEntries(Object.entries(OPTIONS).map(([k, v]) => [v, k]));
const LOGINS = Object.fromEntries(Object.entries(config.people).map(([k, p]) => [p.id, k]));

export function fakeGitHub({ issue, labels = ["優先"] }) {
  const state = { issue: { comments: [], blockedBy: [], subIssues: [], assignees: [], labels: [], state: "OPEN", ...issue }, writes: [] };
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
  const node = () => {
    const i = state.issue;
    return {
      id: "I_1", number: i.number, title: "題名", body: i.body ?? "本文", url: `https://github.com/${config.repository}/issues/${i.number}`,
      state: i.state, stateReason: null, author: { login: "x", databaseId: i.authorId }, parent: i.parent ?? null,
      assignees: { nodes: i.assignees.map((login) => ({ login })) }, labels: { nodes: i.labels.map((name) => ({ name })) }, blockedBy: { nodes: i.blockedBy },
      subIssues: { nodes: i.subIssues }, repository: { nameWithOwner: config.repository },
      comments: { nodes: i.comments.map((c, k) => ({ id: `C_${k}`, url: `u#${k}`, isMinimized: false, ...c })) },
      projectItems: { nodes: [{ id: "PVTI_1", project: { id: "PVT_1" }, fieldValueByName: i.status ? { name: i.status } : null }] },
    };
  };
  const graphql = ({ query, variables }) => {
    const op = /^(query|mutation) (\w+)/.exec(query)[2];
    if (op === "Project")
      return { organization: { projectV2: { id: "PVT_1", field: { id: "F_1", options: Object.entries(OPTIONS).map(([name, id]) => ({ id, name })) } } } };
    if (op === "Issue") return variables.id ? { node: node() } : { repository: { issue: node() } };
    if (op === "Set") state.issue.status = NAMES[variables.o];
    if (op === "Clear") state.issue.status = null;
    state.writes.push({ op, ...variables });
    return { ok: true };
  };
  globalThis.fetch = async (url, init = {}) => {
    const path = new URL(url).pathname, method = init.method ?? "GET";
    const body = init.body ? JSON.parse(init.body) : null;
    const auth = init.headers.authorization;
    if (path === `/repos/${config.repository}/installation`) return json({ id: 7 });
    if (path.endsWith("/access_tokens")) return json({ token: "app-token" });
    if (path === "/graphql") return json({ data: graphql(body) });
    if (path.startsWith("/user/")) return json({ login: LOGINS[Number(path.slice(6))] });
    if (method === "GET" && path.startsWith(`/repos/${config.repository}/labels/`))
      return labels.includes(decodeURIComponent(path.split("/labels/")[1])) ? json({}) : json({}, 404);
    state.writes.push({ method, path, body, as: auth === "Bearer form-token" ? "hidakagit" : "gate" });
    if (method === "POST" && path.endsWith("/labels")) state.issue.labels.push(...body.labels);
    if (method === "DELETE" && path.includes("/labels/")) state.issue.labels = state.issue.labels.filter((l) => l !== decodeURIComponent(path.split("/labels/")[1]));
    if (method === "PATCH" && body.assignees) state.issue.assignees = body.assignees;
    if (method === "PATCH" && body.state) state.issue.state = body.state.toUpperCase();
    if (method === "PATCH" && "body" in body) state.issue.body = body.body;
    if (path.endsWith("/comments")) {
      state.issue.comments.push({ body: body.body, author: { login: auth === "Bearer form-token" ? "hidakagit" : "ridecompass-gate" } });
      return json({ node_id: "C_new", html_url: "u#new" }, 201);
    }
    return json({});
  };
  return state;
}

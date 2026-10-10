// GitHub への読み書き。ゲートは App（env.APP_ID・PKCS#8 の env.APP_KEY）の名義、道具と回答フォームはトークンの名義。
const API = "https://api.github.com";
const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const tokens = new Map();
// 一時的な失敗（5xx・接続の失敗・GraphQL の「Something went wrong while executing your query」）を打ち直すまでの秒数。数と間と、
// GraphQL のどの失敗を一時的とみるかは、GitHub の公式の SDK の打ち直し（octokit/plugin-retry.js の既定）に合わせる。
const AGAIN = [1, 4, 9];
const transient = (message) => Object.assign(new Error(message), { transient: true });

// 読むだけの要求（read）は、一時的な失敗なら AGAIN の間をあけて打ち直す。書く要求は打ち直さない——失敗の応答でも書き込みが
// 通っていることがある（問いのコメントと移動を1回で書いた要求が 502 を受け、コメントは書かれていた）。打ち直して同じ結果に
// なるようにするのは、書く側の道具が持つ（src/move.js: askTask）。
export async function again(read, call) {
  for (let i = 0; ; i++) {
    try {
      return await call();
    } catch (e) {
      if (!read || !e.transient || i === AGAIN.length) throw e;
      await new Promise((r) => setTimeout(r, AGAIN[i] * 1e3));
    }
  }
}

export class GitHub {
  constructor(token) {
    this.token = token;
  }

  // インストールのトークンは1時間有効なので、切れる5分前まで使い回す。
  static async asApp(env, installation) {
    const hit = tokens.get(installation);
    if (hit && hit.expires - Date.now() > 300e3) return new GitHub(hit.token);
    const der = Uint8Array.from(atob(env.APP_KEY.replace(/-----[^-]+-----|\s+/g, "")), (c) => c.charCodeAt(0));
    const key = await crypto.subtle.importKey("pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
    const now = Math.floor(Date.now() / 1000);
    const part = (o) => b64url(new TextEncoder().encode(JSON.stringify(o)));
    const data = `${part({ alg: "RS256", typ: "JWT" })}.${part({ iat: now - 60, exp: now + 540, iss: String(env.APP_ID) })}`;
    const jwt = `${data}.${b64url(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(data)))}`;
    const t = await new GitHub(jwt).rest("POST", `/app/installations/${installation}/access_tokens`);
    tokens.set(installation, { token: t.token, expires: Date.parse(t.expires_at) });
    return new GitHub(t.token);
  }

  // path は API の中の道か、応答が返した URL（リリースの upload_url 等）。type が JSON でなければ body をそのまま送る。
  // read（既定は GET）は読むだけの要求で、一時的な失敗なら打ち直す（again）。
  text(method, path, body, type = "application/json", read = method === "GET") {
    return again(read, () => this.once(method, path, body, type));
  }

  async once(method, path, body, type) {
    const res = await fetch(path.startsWith("https://") ? path : API + path, {
      method,
      headers: { authorization: `Bearer ${this.token}`, accept: "application/vnd.github+json", "x-github-api-version": "2022-11-28", "user-agent": "ridecompass-gate", "content-type": type },
      body: body && type === "application/json" ? JSON.stringify(body) : body,
    }).catch((e) => { throw transient(e.message); });
    const text = await res.text();
    if (!res.ok) throw Object.assign(new Error(`GitHub ${method} ${path}: ${res.status} ${text.slice(0, 200)}`), { transient: res.status >= 500 });
    return text;
  }

  async rest(method, path, body, type) {
    const text = await this.text(method, path, body, type);
    return text ? JSON.parse(text) : null;
  }

  // Markdown を GitHub の issue と同じ描き方で HTML にする（危ない HTML は GitHub が取り除く）。
  markdown(text, repository) {
    return this.text("POST", "/markdown", { text, mode: "gfm", context: repository }, undefined, true);
  }

  gql(query, variables = {}) {
    return again(query.startsWith("query"), async () => {
      const r = JSON.parse(await this.once("POST", "/graphql", { query, variables }, "application/json"));
      if (!r.errors) return r.data;
      const message = r.errors.map((e) => e.message).join(" / ");
      throw Object.assign(new Error(`GitHub GraphQL: ${message}`), { transient: /Something went wrong while executing your query/.test(message) });
    });
  }

  // 書き込み（[名前, 入力] の並び）を1回の要求で、並べた順に行う。
  write(ops) {
    if (!ops.length) return null;
    const decl = ops.map(([name], i) => `$m${i}: ${name[0].toUpperCase()}${name.slice(1)}Input!`).join(", ");
    return this.gql(`mutation Batch(${decl}) { ${ops.map(([name], i) => `m${i}: ${name}(input: $m${i}) { clientMutationId }`).join(" ")} }`,
      Object.fromEntries(ops.map(([, input], i) => [`m${i}`, input])));
  }
}

const TASK = `fragment Task on Issue { id number title body url state author { ... on User { databaseId } } parent { number } issueType { id name }
  assignees(first: 5) { nodes { id login } } labels(first: 20) { nodes { name } }
  blockedBy(first: 50) { nodes { number state } }
  lastClose: timelineItems(last: 1, itemTypes: [CLOSED_EVENT]) { nodes { ... on ClosedEvent { stateReason } } }
  comments(last: $c) { nodes { author { login } createdAt url body bodyHTML } }
  projectItems(first: 10) { nodes { id project { id } fieldValues(first: 30) { nodes {
    ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2SingleSelectField { name } } }
    ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2Field { name } } } } } } }
  repository { id nameWithOwner } }`;
const COMMON = `organization(login: $po) { projectV2(number: $pn) { id fields(first: 50) { nodes {
  ... on ProjectV2SingleSelectField { id name options { id name } } ... on ProjectV2Field { id name dataType } } } } }
  repository(owner: $o, name: $n) { labels(first: 100) { nodes { id name } }`;

// タスクを1回の問い合わせで読む。ref は { number } か { nodeId }。comments は新しいコメントを何件読むか。
// project.fields は欄の名前 → { id, options（単一選択の名前 → id）か date: true }。issue.fields は欄の名前 → 今の値。
// 置き場の issue でなければ issue は null。
export async function readTask(gh, config, ref, { comments = 1 } = {}) {
  const [o, n] = config.repository.split("/");
  const head = "$po: String!, $pn: Int!, $o: String!, $n: String!, $c: Int!";
  const v = { po: config.project.owner, pn: config.project.number, o, n, c: comments };
  const d = ref.nodeId
    ? await gh.gql(`query Task(${head}, $id: ID!) { ${COMMON} } node(id: $id) { ...Task } } ${TASK}`, { ...v, id: ref.nodeId })
    : await gh.gql(`query Task(${head}, $k: Int!) { ${COMMON} issue(number: $k) { ...Task } } } ${TASK}`, { ...v, k: ref.number });
  const p = d.organization.projectV2;
  const project = {
    id: p.id,
    fields: Object.fromEntries(p.fields.nodes.filter((f) => f.options || f.dataType === "DATE")
      .map((f) => [f.name, f.options ? { id: f.id, options: Object.fromEntries(f.options.map((x) => [x.name, x.id])) } : { id: f.id, date: true }])),
  };
  const labels = Object.fromEntries(d.repository.labels.nodes.map((l) => [l.name, l.id]));
  const issue = ref.nodeId ? d.node : d.repository.issue;
  if (issue?.repository?.nameWithOwner !== config.repository) return { project, labels, issue: null };
  const item = issue.projectItems.nodes.find((i) => i.project.id === p.id);
  const set = (item?.fieldValues.nodes ?? []).filter((x) => x.field);
  const fields = Object.fromEntries(set.map((x) => [x.field.name, x.name ?? x.date]));
  return { project, labels, issue: { ...issue, item: item?.id ?? null, status: fields[config.project.statusField] ?? null, fields } };
}

// issue（TASK の形か、見回りの一覧の形）のラベルの名前と、開いた前提があるか。
export const labelNames = (issue) => issue.labels.nodes.map((l) => l.name);
export const blockedOpen = (issue) => issue.blockedBy.nodes.some((b) => b.state !== "CLOSED");
// readTask の issue を、待つ理由の見分け（rules.js: waitsFor）へ渡す形にする。
export const waitsOf = (config, issue) =>
  ({ status: issue.status, blocked: blockedOpen(issue), labels: labelNames(issue), startOn: issue.fields[config.project.startField] ?? null });

// コメントを書く1件。
export const addComment = (subjectId, body) => ["addComment", { subjectId, body }];

// Project の欄を名前で書く1件。単一選択は選択肢の名前、日付は YYYY-MM-DD（消すなら null）。
export function setField(project, item, name, value) {
  const field = project.fields[name];
  const at = { projectId: project.id, itemId: item, fieldId: field?.id };
  if (field?.date && value === null) return ["clearProjectV2ItemFieldValue", at];
  if (field?.date) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(value))) throw new Error(`欄「${name}」は日付の欄です。YYYY-MM-DD の日付を渡してください（「${value}」）。`);
    return ["updateProjectV2ItemFieldValue", { ...at, value: { date: value } }];
  }
  if (!field?.options[value]) throw new Error(`欄「${name}」に選択肢「${value}」がありません（${field ? Object.keys(field.options).join("・") : Object.keys(project.fields).join("・")}）。`);
  return ["updateProjectV2ItemFieldValue", { ...at, value: { singleSelectOptionId: field.options[value] } }];
}

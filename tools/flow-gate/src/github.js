// GitHub への読み書き。ゲートは App（env.APP_ID・env.APP_KEY は PKCS#8）の名義、答えのコメントは env.FORM_TOKEN の名義で書く。
// 1回の出来事・1回の送信で、読むのも書くのも GraphQL の1回ずつにまとめる（呼び出しは1回ごとに往復の時間がかかり、
// 回答フォームはその間あなたを待たせるため）。
const API = "https://api.github.com";
const b64url = (bytes) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function appJwt(env) {
  const der = Uint8Array.from(atob(env.APP_KEY.replace(/-----[^-]+-----|\s+/g, "")), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
  const now = Math.floor(Date.now() / 1000);
  const part = (o) => b64url(new TextEncoder().encode(JSON.stringify(o)));
  const data = `${part({ alg: "RS256", typ: "JWT" })}.${part({ iat: now - 60, exp: now + 540, iss: String(env.APP_ID) })}`;
  return `${data}.${b64url(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(data)))}`;
}

const tokens = new Map();

export class GitHub {
  constructor(token) {
    this.token = token;
  }

  // インストールのトークンは1時間有効。同じ Worker の中で続く要求には、切れる5分前まで使い回す。
  static async asApp(env, installationId) {
    const hit = tokens.get(installationId);
    if (hit && hit.expires - Date.now() > 5 * 60 * 1000) return new GitHub(hit.token);
    const app = new GitHub(await appJwt(env));
    const t = await app.rest("POST", `/app/installations/${installationId}/access_tokens`);
    tokens.set(installationId, { token: t.token, expires: Date.parse(t.expires_at) });
    return new GitHub(t.token);
  }

  async rest(method, path, body) {
    const res = await fetch(API + path, {
      method,
      headers: {
        authorization: `Bearer ${this.token}`,
        accept: "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
        "user-agent": "ridecompass-gate",
        ...(body ? { "content-type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`GitHub ${method} ${path}: ${res.status} ${text.slice(0, 200)}`);
    return text ? JSON.parse(text) : null;
  }

  async gql(query, variables = {}) {
    const r = await this.rest("POST", "/graphql", { query, variables });
    if (r.errors) throw new Error(`GitHub GraphQL: ${r.errors.map((e) => e.message).join(" / ")}`);
    return r.data;
  }
}

// 書き込みを GraphQL の1回の要求にまとめる。並べた順に実行される。入力の型は GitHub の命名（<名前>Input）に従う。
export class Mutations {
  constructor() {
    this.parts = [];
    this.vars = {};
  }

  add(name, input, select = "clientMutationId") {
    const key = `m${this.parts.length}`;
    this.parts.push({ key, name, select });
    this.vars[key] = input;
    return this;
  }

  async send(gh) {
    if (!this.parts.length) return {};
    const decl = this.parts.map(({ key, name }) => `$${key}: ${name[0].toUpperCase()}${name.slice(1)}Input!`).join(", ");
    const body = this.parts.map(({ key, name, select }) => `${key}: ${name}(input: $${key}) { ${select} }`).join(" ");
    return gh.gql(`mutation Batch(${decl}) { ${body} }`, this.vars);
  }
}

const TASK = `fragment Task on Issue { id number title body url state stateReason author { login ... on User { databaseId } }
  parent { number } assignees(first: 5) { nodes { id login } } labels(first: 20) { nodes { name } }
  blockedBy(first: 50) { nodes { number state stateReason } } subIssues(first: 50) { nodes { state } }
  lastClose: timelineItems(last: 1, itemTypes: [CLOSED_EVENT]) { nodes { ... on ClosedEvent { stateReason } } }
  projectItems(first: 10) { nodes { id project { id } fieldValues(first: 30) { nodes {
    ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2SingleSelectField { name } } } } } } }
  repository { nameWithOwner } }`;
const COMMON = `organization(login: $po) { projectV2(number: $pn) { id fields(first: 50) { nodes { ... on ProjectV2SingleSelectField { id name options { id name } } } } } }
  repository(owner: $o, name: $n) { labels(first: 100) { nodes { id name } }`;

// タスクを、判断と書き込みに要るだけ1回の問い合わせで読む（Project の単一選択の欄・置き場のラベル・issue）。
// project.fields は欄の名前 → { id, options: 選択肢の名前 → id, order: 選択肢の並び }、issue.fields は欄の名前 → 今の値。
// Project の件は設定の Project のものだけを見る。issue が置き場のものでなければ issue は null。
export async function readTask(gh, config, ref) {
  const [o, n] = config.repository.split("/");
  const v = { po: config.project.owner, pn: config.project.number, o, n };
  const head = "$po: String!, $pn: Int!, $o: String!, $n: String!";
  const d = ref.nodeId
    ? await gh.gql(`query Task(${head}, $id: ID!) { ${COMMON} } node(id: $id) { ...Task } } ${TASK}`, { ...v, id: ref.nodeId })
    : await gh.gql(`query Task(${head}, $k: Int!) { ${COMMON} issue(number: $k) { ...Task } } } ${TASK}`, { ...v, k: ref.number });
  const p = d.organization.projectV2;
  const fields = Object.fromEntries(
    p.fields.nodes.filter((f) => f.options).map((f) => [f.name, { id: f.id, options: Object.fromEntries(f.options.map((x) => [x.name, x.id])), order: f.options.map((x) => x.name) }]),
  );
  const status = fields[config.project.statusField];
  const project = { id: p.id, field: status.id, options: status.options, fields };
  const labels = Object.fromEntries(d.repository.labels.nodes.map((l) => [l.name, l.id]));
  const issue = ref.nodeId ? d.node : d.repository.issue;
  if (!issue || issue.repository?.nameWithOwner !== config.repository) return { project, labels, issue: null };
  const item = issue.projectItems.nodes.find((i) => i.project.id === project.id);
  const values = Object.fromEntries((item?.fieldValues.nodes ?? []).filter((x) => x.field).map((x) => [x.field.name, x.name]));
  return { project, labels, issue: { ...issue, item: item?.id ?? null, status: values[config.project.statusField] ?? null, fields: values } };
}

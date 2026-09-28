// GitHub への読み書き。ゲートは App（env.APP_ID・env.APP_KEY は PKCS#8）の名義、答えのコメントは env.FORM_TOKEN の名義で書く。
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

export class GitHub {
  constructor(token) {
    this.token = token;
  }

  // installationId が無ければ、置き場のリポジトリに入っているインストールを引く。
  static async asApp(env, repository, installationId) {
    const jwt = await appJwt(env);
    const app = new GitHub(jwt);
    const id = installationId ?? (await app.rest("GET", `/repos/${repository}/installation`)).id;
    return new GitHub((await app.rest("POST", `/app/installations/${id}/access_tokens`)).token);
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

const ISSUE_FIELDS = `id number title body url state stateReason author { login ... on User { databaseId } }
  parent { number } assignees(first: 5) { nodes { login databaseId } }
  blockedBy(first: 50) { nodes { number state stateReason } }
  subIssues(first: 50) { nodes { id number state } }
  comments(last: 50) { nodes { id url body isMinimized author { login ... on User { databaseId } } } }
  projectItems(first: 10) { nodes { id project { id }
    fieldValueByName(name: $field) { ... on ProjectV2ItemFieldSingleSelectValue { name } } } }`;

// タスクを判断に要るだけ読む。Project の件は設定の Project のものだけを見る。
export async function readIssue(gh, config, project, ref) {
  const d = ref.nodeId
    ? await gh.gql(`query Issue($id: ID!, $field: String!) { node(id: $id) { ... on Issue { ${ISSUE_FIELDS} repository { nameWithOwner } } } }`, {
        id: ref.nodeId,
        field: config.project.statusField,
      })
    : await gh.gql(
        `query Issue($o: String!, $n: String!, $k: Int!, $field: String!) { repository(owner: $o, name: $n) { issue(number: $k) { ${ISSUE_FIELDS} repository { nameWithOwner } } } }`,
        { o: config.repository.split("/")[0], n: config.repository.split("/")[1], k: ref.number, field: config.project.statusField },
      );
  const issue = ref.nodeId ? d.node : d.repository.issue;
  if (!issue || issue.repository.nameWithOwner !== config.repository) return null;
  const item = issue.projectItems.nodes.find((i) => i.project.id === project.id);
  return { ...issue, item: item?.id ?? null, status: item?.fieldValueByName?.name ?? null };
}

// 設定の Project の ID と Status の欄・選択肢の ID。
export async function readProject(gh, config) {
  const d = await gh.gql(
    `query Project($o: String!, $n: Int!, $field: String!) { organization(login: $o) { projectV2(number: $n) { id
      field(name: $field) { ... on ProjectV2SingleSelectField { id options { id name } } } } } }`,
    { o: config.project.owner, n: config.project.number, field: config.project.statusField },
  );
  const p = d.organization.projectV2;
  return { id: p.id, field: p.field.id, options: Object.fromEntries(p.field.options.map((o) => [o.name, o.id])) };
}

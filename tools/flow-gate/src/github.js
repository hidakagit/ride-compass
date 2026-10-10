import { runOf, startAt } from "./rules.js";

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
// なるようにするのは、書く側の道具が持つ（src/ask.js: askTask）。
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

  // App が repository（所有者/名前）に入れてあるインストールの名義。置き場とコードのリポジトリは所有者が違い、インストールも別なので、
  // リポジトリから引く。インストールのトークンは1時間有効なので、切れる5分前まで使い回す。
  static async asApp(env, repository) {
    const hit = tokens.get(repository);
    if (hit && hit.expires - Date.now() > 300e3) return new GitHub(hit.token);
    const der = Uint8Array.from(atob(env.APP_KEY.replace(/-----[^-]+-----|\s+/g, "")), (c) => c.charCodeAt(0));
    const key = await crypto.subtle.importKey("pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
    const now = Math.floor(Date.now() / 1000);
    const part = (o) => b64url(new TextEncoder().encode(JSON.stringify(o)));
    const data = `${part({ alg: "RS256", typ: "JWT" })}.${part({ iat: now - 60, exp: now + 540, iss: String(env.APP_ID) })}`;
    const app = new GitHub(`${data}.${b64url(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(data)))}`);
    const { id } = await app.rest("GET", `/repos/${repository}/installation`);
    const t = await app.rest("POST", `/app/installations/${id}/access_tokens`);
    tokens.set(repository, { token: t.token, expires: Date.parse(t.expires_at) });
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

  // 書き込み（[名前, 入力] の並び）を1回の要求で、並べた順に行う。返すのは名前ごとの結果の並び。
  async write(ops, fields = {}) {
    if (!ops.length) return [];
    const decl = ops.map(([name], i) => `$m${i}: ${name[0].toUpperCase()}${name.slice(1)}Input!`).join(", ");
    const d = await this.gql(`mutation Batch(${decl}) { ${ops.map(([name], i) => `m${i}: ${name}(input: $m${i}) { ${fields[name] ?? "clientMutationId"} }`).join(" ")} }`,
      Object.fromEntries(ops.map(([, input], i) => [`m${i}`, input])));
    return ops.map((_, i) => d[`m${i}`]);
  }
}

const TASK = `fragment Task on Issue { id number title body url state author { ... on User { databaseId } } parent { number } issueType { id name }
  assignees(first: 5) { nodes { id login } } labels(first: 20) { nodes { name } }
  blockedBy(first: 50) { nodes { id number state } }
  lastClose: timelineItems(last: 1, itemTypes: [CLOSED_EVENT]) { nodes { ... on ClosedEvent { stateReason } } }
  comments(last: $c) { nodes { author { login } createdAt url body bodyHTML } }
  projectItems(first: 10) { nodes { id project { id title } fieldValues(first: 30) { nodes {
    ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2SingleSelectField { name } } }
    ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2Field { name } } } } } } }
  repository { id nameWithOwner } }`;
const COMMON = `organization(login: $po) { projectV2(number: $pn) { id fields(first: 50) { nodes {
  ... on ProjectV2SingleSelectField { id name options { id name } } ... on ProjectV2Field { id name dataType } } } } }
  repository(owner: $o, name: $n) { labels(first: 100) { nodes { id name } }`;

// タスクを1回の問い合わせで読む。ref は { number } か { nodeId }。comments は新しいコメントを何件読むか。
// project.fields は欄の名前 → { id, options（単一選択の名前 → id）か start: true（着手可能日時の文字の欄） }。issue.fields は欄の名前 → 今の値。
// issue.item は Actions のボードの項目、issue.dialog は対話作業のボードに載っているか。置き場の issue でなければ issue は null。
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
    fields: Object.fromEntries(p.fields.nodes.filter((f) => f.options || f.name === config.project.startField)
      .map((f) => [f.name, f.options ? { id: f.id, options: Object.fromEntries(f.options.map((x) => [x.name, x.id])) } : { id: f.id, start: true }])),
  };
  const labels = Object.fromEntries(d.repository.labels.nodes.map((l) => [l.name, l.id]));
  const issue = ref.nodeId ? d.node : d.repository.issue;
  if (issue?.repository?.nameWithOwner !== config.repository) return { project, labels, issue: null };
  const item = issue.projectItems.nodes.find((i) => i.project.id === p.id);
  const set = (item?.fieldValues.nodes ?? []).filter((x) => x.field);
  const fields = Object.fromEntries(set.map((x) => [x.field.name, x.name ?? x.text]));
  const dialog = issue.projectItems.nodes.some((i) => i.project.title === config.dialog.title);
  return { project, labels, issue: { ...issue, item: item?.id ?? null, dialog, status: fields[config.project.statusField] ?? null, fields } };
}

// issue（TASK の形か、見回りの一覧の形）のラベルの名前と、開いた前提があるか。
export const labelNames = (issue) => issue.labels.nodes.map((l) => l.name);
export const blockedOpen = (issue) => issue.blockedBy.nodes.some((b) => b.state !== "CLOSED");

// コメントを書く1件。
export const addComment = (subjectId, body) => ["addComment", { subjectId, body }];

// Project の欄を名前で書く1件。単一選択は選択肢の名前、着手可能日時は rules.js: startAt の形（YYYY-MM-DD HH:MM にそろえて書く。消すなら null）。
export function setField(project, item, name, value) {
  const field = project.fields[name];
  const at = { projectId: project.id, itemId: item, fieldId: field?.id };
  if (field?.start && value === null) return ["clearProjectV2ItemFieldValue", at];
  if (field?.start) {
    const start = startAt(value);
    if (!start) throw new Error(`欄「${name}」は日本時間の日時の欄です。YYYY-MM-DD HH:MM か、00:00 なら YYYY-MM-DD を渡してください（「${value}」）。`);
    return ["updateProjectV2ItemFieldValue", { ...at, value: { text: start } }];
  }
  if (!field?.options[value]) throw new Error(`欄「${name}」に選択肢「${value}」がありません（${field ? Object.keys(field.options).join("・") : Object.keys(project.fields).join("・")}）。`);
  return ["updateProjectV2ItemFieldValue", { ...at, value: { singleSelectOptionId: field.options[value] } }];
}

// 対話作業のボード（{ id, number, viewerCanUpdate（読んだ名義が書けるか） }。無ければ undefined）と、issue の種類の名前 → id。対話作業のボードは題名（dialog.title）で引く: 番号は
// 作ったときに GitHub が決めるので、設定に書くと作る順で変わる。
export const dialogBoard = async (gh, config) => (await gh.gql("query Board($o: String!, $t: String!) { organization(login: $o) { projectsV2(first: 20, query: $t) { nodes { id number title viewerCanUpdate } } } }",
  { o: config.project.owner, t: config.dialog.title })).organization.projectsV2.nodes.find((p) => p.title === config.dialog.title);
export const typeIds = async (gh, config) => Object.fromEntries((await gh.gql("query Types($o: String!) { organization(login: $o) { issueTypes(first: 50) { nodes { id name } } } }",
  { o: config.project.owner })).organization.issueTypes.nodes.map((t) => [t.name, t.id]));

// 段階を作る: 親の子（sub-issue）として、親と同じ種類（dialog なら対話作業の種類）で作り、前の段階（before。TASK の形）を段階の前提に、
// 段階を親の前提に張る。ボードへ入れるのは、作られた出来事を受けたゲート。
export async function createStage(gh, config, parent, { title, body, before = [], dialog = false }) {
  const issueTypeId = dialog ? (await typeIds(gh, config))[config.dialog.type] : parent.issueType?.id;
  const stage = (await gh.gql("mutation C($i: CreateIssueInput!) { createIssue(input: $i) { issue { id number url } } }",
    { i: { repositoryId: parent.repository.id, parentIssueId: parent.id, issueTypeId, title, body } })).createIssue.issue;
  await gh.write([...before.map((b) => ["addBlockedBy", { issueId: stage.id, blockingIssueId: b.id }]), ["addBlockedBy", { issueId: parent.id, blockingIssueId: stage.id }]]);
  return stage;
}

// 担当のワークフローの終わっていない実行（{ id, number, kind, url }）。一覧は新しい順で1回に100件までなので、終わっていない状態ごとに
// 絞って全部のページを読む（長く動く実行が新しい実行の後ろへ押し出されても数える）。状態は実行が移る順に読み、読んでいる間に次の状態へ
// 移った実行も後の状態で拾う（同じ実行は後で読んだ方を採る）。pending は同じ組の前の実行を待っているもの。get はパスを受けて応答を返す。
export async function readActive(get, config) {
  const runs = new Map();
  for (const status of ["requested", "queued", "pending", "waiting", "in_progress"]) {
    for (let page = 1; ; page++) {
      const { workflow_runs: rs } = await get(`/repos/${config.code.repository}/actions/workflows/${config.coordinator.workflow}/runs?status=${status}&per_page=100&page=${page}`);
      for (const r of rs) runs.set(r.id, r);
      if (rs.length < 100) break;
    }
  }
  return [...runs.values()].map((r) => {
    const [number, kind] = runOf(r.display_title);
    return { ...r, number: Number(number), kind, url: r.html_url };
  });
}

const ok = (c) => ["success", "skipped", "neutral"].includes(c.conclusion);

// 作業ブランチ（branch）の PR の事実: open（開いた PR: { id, draft, ci, demoted } か null）・merged（マージした PR があるか）。ci は開いた下書きの
// PR の先頭のコミットの CI: 必須のチェック（master のルールセット）と変異テスト（code.mutation。走っていれば）が全部終わるまで pending、
// どれかが成功・飛ばし以外で終わったか変異テストに前の回（前のコミット）に無い生き残りの注記があれば fail、ほかは pass。demoted は、
// CI が終わったあとに下書きへ戻された（差し戻し）か。
export async function readPull(gh, config, branch) {
  const { repository: code, mutation } = config.code;
  const [o, n] = code.split("/");
  const d = await gh.gql(`query Pulls($o: String!, $n: String!, $b: String!) { repository(owner: $o, name: $n) { pullRequests(headRefName: $b, states: [OPEN, MERGED], last: 5) {
    nodes { id number isDraft state headRefOid timelineItems(last: 1, itemTypes: [CONVERT_TO_DRAFT_EVENT]) { nodes { ... on ConvertToDraftEvent { createdAt } } }
    commits(last: 30) { nodes { commit { oid } } } } } } }`, { o, n, b: branch });
  const prs = d.repository.pullRequests.nodes;
  const pr = prs.find((p) => p.state === "OPEN");
  const merged = prs.some((p) => p.state === "MERGED");
  if (!pr?.isDraft) return { open: pr ? { id: pr.id, draft: false } : null, merged };
  const checks = async (sha) => (await gh.rest("GET", `/repos/${code}/commits/${sha}/check-runs?per_page=100`)).check_runs;
  const survivors = async (run) => new Set((await gh.rest("GET", `/repos/${code}/check-runs/${run.id}/annotations?per_page=100`))
    .filter((a) => a.title === mutation.title).map((a) => `${a.path}\n${a.message}`));
  const rules = await gh.rest("GET", `/repos/${code}/rules/branches/${config.code.base}`);
  const required = rules.filter((r) => r.type === "required_status_checks").flatMap((r) => r.parameters.required_status_checks.map((c) => c.context));
  const head = await checks(pr.headRefOid);
  const want = [...required.map((name) => head.find((c) => c.name === name)), ...head.filter((c) => c.name === mutation.check)];
  const open = { id: pr.id, draft: true, ci: "pending", demoted: false };
  if (want.some((c) => !c || c.status !== "completed")) return { open, merged };
  open.ci = want.some((c) => !ok(c)) ? "fail" : "pass";
  const run = head.find((c) => c.name === mutation.check);
  if (open.ci === "pass" && run) {
    const before = pr.commits.nodes.map((c) => c.commit.oid).filter((sha) => sha !== pr.headRefOid).reverse();
    let seen = new Set();
    for (const sha of before) {
      const prev = (await checks(sha)).find((c) => c.name === mutation.check);
      if (prev) {
        seen = await survivors(prev);
        break;
      }
    }
    if ([...(await survivors(run))].some((s) => !seen.has(s))) open.ci = "fail";
  }
  const converted = pr.timelineItems.nodes[0]?.createdAt;
  open.demoted = Boolean(converted) && converted > want.map((c) => c.completed_at).sort().at(-1);
  return { open, merged };
}

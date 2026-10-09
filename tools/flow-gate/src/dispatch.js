// 振り出しの見回りの1周の判断と、Project の状況の更新の書き込み。
import { waitsUntil } from "./rules.js";

const ITEMS = `query Items($o: String!, $n: Int!, $q: String!, $st: String!, $p: String!, $s: String!, $c: String) {
  organization(login: $o) { projectV2(number: $n) { field(name: $p) { ... on ProjectV2SingleSelectField { options { name } } }
  items(first: 100, after: $c, query: $q) { pageInfo { hasNextPage endCursor } nodes {
    status: fieldValueByName(name: $st) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    priority: fieldValueByName(name: $p) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    start: fieldValueByName(name: $s) { ... on ProjectV2ItemFieldDateValue { date } }
    content { ... on Issue { number labels(first: 20) { nodes { name } } blockedBy(first: 50) { nodes { state } } } } } } } } }`;

// Project のタスクを読む（query は Project の絞り込み。開いたものは "is:open"）。ranks は優先度の欄の選択肢の並び。
export async function readTasks(gh, config, query) {
  const { owner, number, statusField, priorityField, startField, urgentLabel } = config.project;
  const tasks = [];
  let ranks = [];
  for (let c = null; ; ) {
    const p = (await gh.gql(ITEMS, { o: owner, n: number, q: query, st: statusField, p: priorityField, s: startField, c })).organization.projectV2;
    ranks = p.field?.options.map((o) => o.name) ?? [];
    for (const { content: t, status, priority, start } of p.items.nodes.filter((i) => i.content?.number)) {
      const labels = t.labels.nodes.map((l) => l.name);
      tasks.push({
        number: t.number, status: status?.name ?? null, labels, urgent: labels.includes(urgentLabel), priority: priority?.name ?? null,
        startOn: start?.date ?? null, blocked: t.blockedBy.nodes.some((b) => b.state !== "CLOSED"),
      });
    }
    if (!p.items.pageInfo.hasNextPage) return { tasks, ranks };
    c = p.items.pageInfo.endCursor;
  }
}

// 担当の種類はステータスで決まる。実行の名前（run-name）は「#<番号> <種類>」。
const kindOf = (config, status) => ({ [config.todo]: "作る", [config.review]: "確かめる" })[status];
export const runOf = (title) => (/^#(\d+) (\S+)$/.exec(title ?? "") ?? []).slice(1);

// 担当のワークフローの終わっていない実行（GitHub の実行の形のまま）。一覧は新しい順で1回に100件までなので、終わっていない状態ごとに
// 絞って全部のページを読む（長く動く実行が新しい実行の後ろへ押し出されても数える）。状態は実行が移る順に読み、読んでいる間に次の状態へ
// 移った実行も後の状態で拾う（同じ実行は後で読んだ方を採る）。pending は同じグループの前の実行を待っているもの。get はパスを受けて応答を返す。
export async function readActive(get, config) {
  const runs = new Map();
  for (const status of ["requested", "queued", "pending", "waiting", "in_progress"]) {
    for (let page = 1; ; page++) {
      const { workflow_runs: rs } = await get(`/repos/${config.code.repository}/actions/workflows/${config.coordinator.workflow}/runs?status=${status}&per_page=100&page=${page}`);
      for (const r of rs) runs.set(r.id, r);
      if (rs.length < 100) break;
    }
  }
  return [...runs.values()];
}

// 振り出せるもの: 確かめるは検証中の全部。作るは未着手のうち、前提が全部閉じ、ラベル coordinator.devLabel が無く、着手可能日が
// 今日以前のもの。動いている番号は除く。並びは「急ぎ」→ 優先度の欄の選択肢の順（空は project.unsetPriority の位置）→ 番号の小さい順。
export function ready(config, { tasks, ranks }, running, now = new Date()) {
  const rank = (p) => ranks.indexOf(p ?? config.project.unsetPriority);
  return tasks
    .filter((t) => kindOf(config, t.status) && !running.some((r) => r.number === t.number))
    .filter((t) => t.status === config.review || (!t.blocked && !t.labels.includes(config.coordinator.devLabel) && !waitsUntil(t.startOn, now)))
    .sort((a, b) => b.urgent - a.urgent || rank(a.priority) - rank(b.priority) || a.number - b.number)
    .map((t) => ({ number: t.number, kind: kindOf(config, t.status) }));
}

// 種類ごとに、枠（coordinator.slots）から動いている数を引いた分だけ上から選ぶ。
export function pick(config, candidates, running) {
  const free = Object.fromEntries(Object.entries(config.coordinator.slots).map(([kind, n]) => [kind, n - running.filter((r) => r.kind === kind).length]));
  return candidates.filter((t) => free[t.kind]-- > 0);
}

// 状況の更新の中身。気づくべきもの（進行中なのに動いている担当が無いタスク・振り出せる仕事があるのに空いた枠・一番新しい実行が
// 失敗したタスク）があれば At risk。runs は担当の実行の新しい順（終わったものは conclusion を持つ）、idle は枠が空いている理由（無ければ null）。
export function summary(config, { watcher, tasks, runs, started, waiting, idle }) {
  const latest = new Map();
  for (const r of runs) if (!latest.has(r.number)) latest.set(r.number, r);
  const notes = [
    ...tasks.filter((t) => t.status === config.working && !runs.some((r) => r.number === t.number && !r.conclusion)).map((t) => `- #${t.number} が${config.working}なのに、動いている担当が無い`),
    ...(idle ? [`- 振り出せる仕事があるのに枠が空いている: ${idle}`] : []),
    ...[...latest.values()].filter((r) => r.conclusion === "failure" && tasks.some((t) => t.number === r.number)).map((r) => `- #${r.number} の${r.kind}担当の実行が失敗で終わった [実行](${r.url})`),
  ];
  const lines = [`振り出しの見回り（${watcher}）が書く。中身が変わったときだけ書き換える。`, "", "### 気づくべきもの", ...(notes.length ? notes : ["無し"])];
  for (const [kind, n] of Object.entries(config.coordinator.slots)) {
    const rows = [...runs.filter((r) => r.kind === kind && !r.conclusion).map((r) => `- #${r.number} [実行](${r.url})`), ...started.filter((t) => t.kind === kind).map((t) => `- #${t.number}（いま起こした）`)];
    lines.push("", `### ${kind}担当（${rows.length}/${n}）`, ...(rows.length ? rows : ["無し"]));
  }
  lines.push("", `振り出しを待つ仕事: ${waiting}件`);
  return { status: notes.length ? "AT_RISK" : "ON_TRACK", body: lines.join("\n") };
}

// 状況の更新を書く。最新が見回りのもので中身も同じなら書かず、状態が同じなら書き換え、変わったか最新がほかの者のものなら足す
// （履歴には状態の移り変わりだけが残る）。書いたら true。
export async function putStatus(gh, config, { status, body }) {
  const p = (await gh.gql(`query Updates($o: String!, $n: Int!) { organization(login: $o) { projectV2(number: $n) { id
    statusUpdates(first: 1, orderBy: { field: CREATED_AT, direction: DESC }) { nodes { id status body creator { login } } } } } }`,
    { o: config.project.owner, n: config.project.number })).organization.projectV2;
  const latest = p.statusUpdates.nodes[0];
  const ours = latest?.creator?.login === config.claude && latest.body?.startsWith("振り出しの見回り") ? latest : null;
  if (ours?.status === status && ours.body === body) return false;
  await gh.write([ours?.status === status ? ["updateProjectV2StatusUpdate", { statusUpdateId: ours.id, status, body }] : ["createProjectV2StatusUpdate", { projectId: p.id, status, body }]]);
  return true;
}

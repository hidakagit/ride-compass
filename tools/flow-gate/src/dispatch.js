// 振り出しの見回りの1周の判断と、Project の状況の更新の書き込み。
import { waitsUntil } from "./rules.js";

const ITEMS = `query Items($o: String!, $n: Int!, $q: String!, $st: String!, $p: String!, $sz: String!, $s: String!, $c: String) {
  organization(login: $o) { projectV2(number: $n) { field(name: $p) { ... on ProjectV2SingleSelectField { options { name } } }
  items(first: 100, after: $c, query: $q) { pageInfo { hasNextPage endCursor } nodes {
    status: fieldValueByName(name: $st) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    priority: fieldValueByName(name: $p) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    size: fieldValueByName(name: $sz) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    start: fieldValueByName(name: $s) { ... on ProjectV2ItemFieldDateValue { date } }
    content { ... on Issue { number closedAt labels(first: 20) { nodes { name } } blockedBy(first: 50) { nodes { state } }
      timelineItems(first: 100, itemTypes: [ASSIGNED_EVENT, UNASSIGNED_EVENT]) { nodes { __typename
        ... on AssignedEvent { createdAt assignee { ... on User { login } } } ... on UnassignedEvent { createdAt assignee { ... on User { login } } } } } } } } } } } }`;

// 担当者が Claude だった時間の合計（時間）。担当者の付け外しの履歴を古い順にたどり、until まで足す。
export function claudeHours(config, events, until) {
  const holders = new Set();
  let since = null;
  let total = 0;
  for (const e of events.toSorted((a, b) => a.createdAt.localeCompare(b.createdAt))) {
    if (since !== null) total += Date.parse(e.createdAt) - since;
    holders[e.__typename === "AssignedEvent" ? "add" : "delete"](e.assignee?.login);
    since = holders.has(config.claude) ? Date.parse(e.createdAt) : null;
  }
  return (since === null ? total : total + Date.parse(until) - since) / 3600e3;
}

// Project のタスクを読む（query は Project の絞り込み。開いたものは "is:open"）。ranks は優先度の欄の選択肢の並び。
export async function readTasks(gh, config, query, now = new Date()) {
  const { owner, number, statusField, priorityField, sizeField, startField, urgentLabel } = config.project;
  const tasks = [];
  let ranks = [];
  for (let c = null; ; ) {
    const p = (await gh.gql(ITEMS, { o: owner, n: number, q: query, st: statusField, p: priorityField, sz: sizeField, s: startField, c })).organization.projectV2;
    ranks = p.field?.options.map((o) => o.name) ?? [];
    for (const { content: t, status, priority, size, start } of p.items.nodes.filter((i) => i.content?.number)) {
      const labels = t.labels.nodes.map((l) => l.name);
      tasks.push({
        number: t.number, status: status?.name ?? null, labels, urgent: labels.includes(urgentLabel), priority: priority?.name ?? null, size: size?.name ?? null,
        startOn: start?.date ?? null, blocked: t.blockedBy.nodes.some((b) => b.state !== "CLOSED"), closedAt: t.closedAt,
        claudeHours: claudeHours(config, t.timelineItems.nodes, t.closedAt ?? now.toISOString()),
      });
    }
    if (!p.items.pageInfo.hasNextPage) return { tasks, ranks };
    c = p.items.pageInfo.endCursor;
  }
}

// 規模ごとの想定（時間）: 完成で閉じた同じ規模の直近 coordinator.recent 件の、Claude の番の累計時間の p90。
export function expected(config, done) {
  const bySize = Object.groupBy(done.filter((t) => t.size).toSorted((a, b) => b.closedAt.localeCompare(a.closedAt)), (t) => t.size);
  return Object.fromEntries(Object.entries(bySize).map(([size, v]) => {
    const hours = v.slice(0, config.coordinator.recent).map((t) => t.claudeHours).toSorted((a, b) => a - b);
    return [size, hours[Math.floor(0.9 * hours.length)]];
  }));
}

// 担当の種類はステータスで決まる。実行の名前（run-name）は「#<番号> <種類>」。
const kindOf = (config, status) => ({ [config.todo]: "作る", [config.review]: "確かめる" })[status];
export const runOf = (title) => (/^#(\d+) (\S+)$/.exec(title ?? "") ?? []).slice(1);

// 振り出せるもの: 確かめるは検証中の全部。作るは未着手のうち、前提が全部閉じ、ラベル coordinator.devLabel が無く、着手可能日が
// 今日以前のもの。動いている番号は除く。並びは「急ぎ」→ 優先度の欄の選択肢の順 → 番号の小さい順。
export function ready(config, { tasks, ranks }, running, now = new Date()) {
  const rank = (p) => (ranks.includes(p) ? ranks.indexOf(p) : ranks.length);
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

// 状況の更新の中身。気づくべきもの（想定を超えたタスク・振り出せる仕事があるのに空いた枠・一番新しい実行が失敗したタスク）が
// あれば At risk。runs は担当の実行の新しい順（終わったものは conclusion を持つ）、idle は枠が空いている理由（無ければ null）。
export function summary(config, { watcher, tasks, expected: limit, runs, started, waiting, idle }) {
  const latest = new Map();
  for (const r of runs) if (!latest.has(r.number)) latest.set(r.number, r);
  const notes = [
    ...tasks.filter((t) => config.owner[t.status] === config.claude && t.claudeHours > (limit[t.size] ?? Infinity))
      .map((t) => `- #${t.number}（${t.size}）が想定を超えている: Claude の番の累計 ${Math.round(t.claudeHours)}時間 ／ 想定 ${Math.round(limit[t.size])}時間`),
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

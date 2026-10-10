// 見回りの1周の判断: 振り出しと、ボードと担当の実行の突き合わせ。ステータスは書かない（食い違いはゲートに決め直しを頼む）。
import { blockedOpen, labelNames } from "./github.js";
import { startWaits } from "./rules.js";

const ITEMS = `query Items($o: String!, $n: Int!, $q: String!, $st: String!, $p: String!, $s: String!, $c: String) {
  organization(login: $o) { projectV2(number: $n) { field(name: $p) { ... on ProjectV2SingleSelectField { options { name } } }
  items(first: 100, after: $c, query: $q) { pageInfo { hasNextPage endCursor } nodes {
    status: fieldValueByName(name: $st) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    priority: fieldValueByName(name: $p) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    start: fieldValueByName(name: $s) { ... on ProjectV2ItemFieldTextValue { text } }
    content { ... on Issue { number labels(first: 20) { nodes { name } } blockedBy(first: 50) { nodes { state } } } } } } } } }`;

// Actions のボードのタスクを読む（query は Project の絞り込み。開いたものは "is:open"）。ranks は優先度の欄の選択肢の並び。
export async function readTasks(gh, config, query) {
  const { owner, number, statusField, priorityField, startField, urgentLabel } = config.project;
  const tasks = [];
  for (let c = null; ; ) {
    const p = (await gh.gql(ITEMS, { o: owner, n: number, q: query, st: statusField, p: priorityField, s: startField, c })).organization.projectV2;
    for (const { content: t, status, priority, start } of p.items.nodes.filter((i) => i.content?.number)) {
      tasks.push({ number: t.number, status: status?.name ?? null, urgent: labelNames(t).includes(urgentLabel), priority: priority?.name ?? null, start: start?.text ?? null, blocked: blockedOpen(t) });
    }
    if (!p.items.pageInfo.hasNextPage) return { tasks, ranks: p.field?.options.map((o) => o.name) ?? [] };
    c = p.items.pageInfo.endCursor;
  }
}

// 担当のワークフローを、その番号の種類で起こす。
export const startRun = (gh, config, number, kind) =>
  gh.rest("POST", `/repos/${config.code.repository}/actions/workflows/${config.coordinator.workflow}/dispatches`,
    { ref: config.code.base, inputs: { issue: String(number), kind } });

// 振り出せるもの: 作るは未着手のうち前提が全部閉じて着手可能日時が今以前のもの、確かめるは検証待ちの全部。動いている番号は除く。
// 並びは「急ぎ」→ 優先度の欄の選択肢の順（空は project.unsetPriority の位置）→ 番号の小さい順。
export function ready(config, { tasks, ranks }, running, now = new Date()) {
  const rank = (p) => ranks.indexOf(p ?? config.project.unsetPriority);
  const kind = { [config.status.todo]: "作る", [config.status.ready]: "確かめる" };
  return tasks
    .map((t) => ({ ...t, kind: kind[t.status] }))
    .filter((t) => t.kind && !running.some((r) => r.number === t.number))
    .filter((t) => t.kind === "確かめる" || (!t.blocked && !startWaits(t.start, now)))
    .sort((a, b) => b.urgent - a.urgent || rank(a.priority) - rank(b.priority) || a.number - b.number)
    .map(({ number, kind }) => ({ number, kind }));
}

// 種類ごとに、枠（coordinator.slots）から動いている数を引いた分だけ上から選ぶ。
export function pick(config, candidates, running) {
  const free = Object.fromEntries(Object.entries(config.coordinator.slots).map(([kind, n]) => [kind, n - running.filter((r) => r.kind === kind).length]));
  return candidates.filter((t) => free[t.kind]-- > 0);
}

// ゲートに決め直しを頼む番号（ゲートが出来事を取りこぼしたときの守り）: 担当が持つのにその種類のステータスでない・進行中か検証中なのに
// 担当がいない・CI待ちなのに作業ブランチの CI が動いていない（ciIdle）。active は担当の実行（{ number, kind }）。
export function mismatches(config, tasks, active, ciIdle) {
  const S = config.status;
  const working = { 作る: S.working, 確かめる: S.review };
  return tasks.filter((t) => {
    const run = active.find((r) => r.number === t.number);
    return run ? t.status !== working[run.kind] : [S.working, S.review].includes(t.status) || (t.status === S.ci && ciIdle.has(t.number));
  }).map((t) => t.number);
}

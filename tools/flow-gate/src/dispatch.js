// 振り出しの見回りの1周の判断と、Project の状況の更新の書き込み。
import { waitsFor, worksAfter } from "./rules.js";

const ITEMS = `query Items($o: String!, $n: Int!, $q: String!, $st: String!, $p: String!, $sz: String!, $s: String!, $c: String) {
  organization(login: $o) { projectV2(number: $n) { field(name: $p) { ... on ProjectV2SingleSelectField { options { name } } }
  items(first: 100, after: $c, query: $q) { pageInfo { hasNextPage endCursor } nodes {
    status: fieldValueByName(name: $st) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    priority: fieldValueByName(name: $p) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    size: fieldValueByName(name: $sz) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    start: fieldValueByName(name: $s) { ... on ProjectV2ItemFieldDateValue { date } }
    content { ... on Issue { number labels(first: 20) { nodes { name } } blockedBy(first: 50) { nodes { state } } } } } } } } }`;

// 閉じた issue を更新日の新しい順に（GitHub の IssueOrder は閉じた日では並べられない）。規模は Project の欄から読む。
const CLOSED = `query Closed($o: String!, $n: String!, $sz: String!, $c: String) { repository(owner: $o, name: $n) {
  issues(states: CLOSED, first: 100, after: $c, orderBy: { field: UPDATED_AT, direction: DESC }) { pageInfo { hasNextPage endCursor } nodes {
    number closedAt updatedAt stateReason
    projectItems(first: 10) { nodes { project { number } size: fieldValueByName(name: $sz) { ... on ProjectV2ItemFieldSingleSelectValue { name } } } } } } } }`;

// 作業の記録: コメント（rules.js: notes の形と問い）と閉じ。1つの issue で読めるのは新しい 100 件まで。
const RECORDS = (numbers) => `query Records($o: String!, $n: String!) { repository(owner: $o, name: $n) {
  ${numbers.map((k) => `i${k}: issue(number: ${k}) { ...R }`).join(" ")} } }
  fragment R on Issue { timelineItems(last: 100, itemTypes: [ISSUE_COMMENT, CLOSED_EVENT]) { nodes { __typename
    ... on ClosedEvent { createdAt } ... on IssueComment { createdAt body author { login } } } } }`;

// Project のタスクを読む（query は Project の絞り込み。開いたものは "is:open"）。ranks は優先度の欄の選択肢の並び。
export async function readTasks(gh, config, query) {
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
        startOn: start?.date ?? null, blocked: t.blockedBy.nodes.some((b) => b.state !== "CLOSED"),
      });
    }
    if (!p.items.pageInfo.hasNextPage) return { tasks, ranks };
    c = p.items.pageInfo.endCursor;
  }
}

// 作業時間（時間）: 作業の状態にいた区間の和。区間は記録の始まり（coordinator.recordsSince）より後の着手からで、区間が1つも
// 無ければ null。記録として読むのは Claude とゲートのコメントだけ（GraphQL は App の名義を [bot] を付けずに返す）。
function workHours(config, items, now) {
  const writers = [config.claude, config.gate.replace(/\[bot\]$/, "")];
  let inside = false;
  let since = null;
  let total = null;
  for (const item of items.toSorted((a, b) => a.createdAt.localeCompare(b.createdAt))) {
    const works = item.__typename === "ClosedEvent" ? false : writers.includes(item.author?.login) ? worksAfter(config, item.body) : null;
    if (works === null || works === inside) continue;
    const at = Date.parse(item.createdAt);
    if (works) since = at >= Date.parse(config.coordinator.recordsSince) ? at : null;
    else if (since !== null) total = (total ?? 0) + at - since;
    inside = works;
  }
  if (inside && since !== null) total = (total ?? 0) + now.getTime() - since;
  return total === null ? null : total / 3600e3;
}

// 番号ごとの作業時間（区間の無いものは持たない）。1回の要求で 50 件ずつ読む。
async function readWorkHours(gh, config, numbers, now) {
  const [o, n] = config.repository.split("/");
  const hours = new Map();
  for (let k = 0; k < numbers.length; k += 50) {
    const part = numbers.slice(k, k + 50);
    const r = (await gh.gql(RECORDS(part), { o, n })).repository;
    for (const number of part) {
      const h = workHours(config, r[`i${number}`].timelineItems.nodes, now);
      if (h !== null) hours.set(number, h);
    }
  }
  return hours;
}

// 規模ごとに、記録の始まり（coordinator.recordsSince）より後に完成で閉じた直近 coordinator.recent 件（{ number, size, closedAt }）。
// 閉じた日は更新日より後にならないので、更新日の新しい順に読み、どの規模も「そろった recent 件目の閉じた日」が読んだ中で一番古い
// 更新日以降になるか、一番古い更新日が記録の始まりより前になったら、残りのページは読まない。読む間に更新されてページをまたいで
// 2度出た issue は、番号で1つにする。
async function readRecent(gh, config, sizes) {
  const { recent, recordsSince } = config.coordinator;
  const [o, n] = config.repository.split("/");
  const found = Object.fromEntries(sizes.map((size) => [size, new Map()]));
  const newest = (size) => [...found[size].values()].toSorted((a, b) => b.closedAt.localeCompare(a.closedAt)).slice(0, recent);
  for (let c = null; sizes.length; ) {
    const { nodes, pageInfo } = (await gh.gql(CLOSED, { o, n, sz: config.project.sizeField, c })).repository.issues;
    for (const t of nodes) {
      const size = t.projectItems.nodes.find((i) => i.project.number === config.project.number)?.size?.name;
      if (t.stateReason === "COMPLETED" && t.closedAt >= recordsSince && found[size]) found[size].set(t.number, { number: t.number, size, closedAt: t.closedAt });
    }
    const oldest = nodes.at(-1)?.updatedAt ?? "";
    if (!pageInfo.hasNextPage || oldest < recordsSince || sizes.every((size) => newest(size)[recent - 1]?.closedAt >= oldest)) break;
    c = pageInfo.endCursor;
  }
  return sizes.flatMap(newest);
}

// 作業の状態にいて規模の欄を持つタスク（作業時間を足したもの。区間の無いものは除く）と、その規模の想定（時間）。想定は、完成で
// 閉じた同じ規模の直近 coordinator.recent 件のうち、作業時間を持つものの p90。記録はこの2つの分だけ読む。
export async function workload(gh, config, open, now = new Date()) {
  const working = open.filter((t) => [config.working, config.review].includes(t.status) && t.size);
  const sizes = [...new Set(working.map((t) => t.size))];
  const samples = await readRecent(gh, config, sizes);
  const hours = await readWorkHours(gh, config, [...working, ...samples].map((t) => t.number), now);
  const expected = {};
  for (const size of sizes) {
    const v = samples.filter((t) => t.size === size && hours.has(t.number)).map((t) => hours.get(t.number)).toSorted((a, b) => a - b);
    if (v.length) expected[size] = v[Math.floor(0.9 * v.length)];
  }
  return { tasks: working.filter((t) => hours.has(t.number)).map((t) => ({ ...t, workHours: hours.get(t.number) })), expected };
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
    .filter((t) => t.status === config.review || !waitsFor(config, t, now))
    .sort((a, b) => b.urgent - a.urgent || rank(a.priority) - rank(b.priority) || a.number - b.number)
    .map((t) => ({ number: t.number, kind: kindOf(config, t.status) }));
}

// 種類ごとに、枠（coordinator.slots）から動いている数を引いた分だけ上から選ぶ。
export function pick(config, candidates, running) {
  const free = Object.fromEntries(Object.entries(config.coordinator.slots).map(([kind, n]) => [kind, n - running.filter((r) => r.kind === kind).length]));
  return candidates.filter((t) => free[t.kind]-- > 0);
}

// 状況の更新の中身。気づくべきもの（想定を超えたタスク・進行中なのに動いている担当が無いタスク・振り出せる仕事があるのに空いた枠・
// 一番新しい実行が失敗したタスク）があれば At risk。working と expected は workload の結果、runs は担当の実行の新しい順（終わったものは
// conclusion を持つ）、idle は枠が空いている理由（無ければ null）。
export function summary(config, { watcher, tasks, working, expected, runs, started, waiting, idle }) {
  const latest = new Map();
  for (const r of runs) if (!latest.has(r.number)) latest.set(r.number, r);
  // 1つのタスクは1行にする: 担当の無い進行中のタスクが想定も超えていれば、その行に添える。
  const over = new Map(working.filter((t) => t.workHours > (expected[t.size] ?? Infinity))
    .map((t) => [t.number, `作業時間 ${t.workHours.toFixed(1)}時間 ／ 想定 ${expected[t.size].toFixed(1)}時間`]));
  const stuck = new Set(tasks.filter((t) => t.status === config.working && !runs.some((r) => r.number === t.number && !r.conclusion)).map((t) => t.number));
  const notes = [
    ...[...stuck].map((k) => `- #${k} が${config.working}なのに、動いている担当が無い${over.has(k) ? `（想定も超えている: ${over.get(k)}）` : ""}`),
    ...working.filter((t) => over.has(t.number) && !stuck.has(t.number)).map((t) => `- #${t.number}（${t.size}）が想定を超えている: ${over.get(t.number)}`),
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

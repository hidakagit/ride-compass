// 振り出しの見回り（bin/dispatch.js）の1周の判断。GitHub から読んだものを受け取り、何を起こすかと状況の更新の中身を決める。
import { openBlockers } from "./rules.js";

const BOARD = `query Board($o: String!, $n: Int!, $field: String!, $p: String!, $c: String) { organization(login: $o) { projectV2(number: $n) {
  field(name: $p) { ... on ProjectV2SingleSelectField { options { name } } }
  items(first: 100, after: $c) { pageInfo { hasNextPage endCursor } nodes {
    fieldValueByName(name: $field) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    priority: fieldValueByName(name: $p) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    content { ... on Issue { number title url state labels(first: 20) { nodes { name } }
      blockedBy(first: 50) { nodes { number state stateReason } } subIssues(first: 50) { nodes { number state } } } } } } } } }`;

// Project の開いたタスクを全部読む。ranks は優先度の欄の選択肢の並び。
export async function readBoard(gh, config) {
  const items = [];
  let ranks = [];
  for (let c = null; ; ) {
    const d = await gh.gql(BOARD, { o: config.project.owner, n: config.project.number, field: config.project.statusField, p: config.project.priorityField, c });
    const project = d.organization.projectV2;
    ranks = project.field?.options.map((o) => o.name) ?? [];
    items.push(...project.items.nodes);
    if (!project.items.pageInfo.hasNextPage) break;
    c = project.items.pageInfo.endCursor;
  }
  const tasks = items
    .map((i) => ({ ...i.content, status: i.fieldValueByName?.name, priority: i.priority?.name ?? null }))
    .filter((t) => t.number && t.state === "OPEN")
    .map((t) => ({
      number: t.number,
      status: t.status,
      title: t.title,
      url: t.url,
      labels: t.labels.nodes.map((l) => l.name),
      urgent: t.labels.nodes.some((l) => l.name === config.project.urgentLabel),
      priority: t.priority,
      waitingFor: openBlockers(t.blockedBy.nodes).map((b) => b.number),
      openChildren: t.subIssues.nodes.filter((c) => c.state === "OPEN").map((c) => c.number),
    }));
  return { tasks, ranks };
}

// Claude が振り出すタスク（ステータスが coordinator.order のもの）を、振り出す順に並べる。
// 並び: ステータスの順 → ラベル「急ぎ」（ユーザーの依頼で、優先度の欄より上）→ 優先度の欄の選択肢の順（値の無いものは最後）→ 番号の若い順。
export function queueOf(config, { tasks, ranks }) {
  const order = config.coordinator.order;
  const rank = (p) => (ranks.includes(p) ? ranks.indexOf(p) : ranks.length);
  return tasks
    .filter((t) => order.includes(t.status))
    .sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status) || b.urgent - a.urgent || rank(a.priority) - rank(b.priority) || a.number - b.number);
}

// 枠が空けば振り出せるもの。running は担当のワークフローで動いている（待っているものを含む）issue の番号。
// 動いている番号・前提が開いたままの未着手・子の段階が開いている親（親の仕事は子で進み、子が全部閉じるとゲートが閉じる）・
// 開発機で扱うタスク（ラベル coordinator.devLabel）は飛ばす。
export const ready = (config, queue, running) =>
  queue.filter((t) => !running.has(t.number) && !t.waitingFor.length && !t.openChildren.length && !t.labels.includes(config.coordinator.devLabel));

// 振り出す仕事を、動いているものと合わせて coordinator.parallel を超えない数だけ上から選ぶ。
// 担当の種類はステータスで決まる（未着手は作る、検証中は確かめる）。
export function pick(config, queue, running) {
  const todo = config.transitions.find((t) => t.on === "振り出し").from[0];
  return ready(config, queue, running)
    .slice(0, Math.max(0, config.coordinator.parallel - running.size))
    .map((t) => ({ number: t.number, status: t.status, kind: t.status === todo ? "作る" : "確かめる" }));
}

// 担当のワークフローの実行の名前（run-name）は「#<番号> <種類>」。名前から番号を読む。
export const runIssue = (title) => Number(/^#(\d+) /.exec(title ?? "")?.[1]) || null;

// 止まっているもの: 進行中なのに担当が動いていない（子の段階が開いている親は除く）・検証中なのに開いた Pull Request が無い。
// openBranches はコードのリポジトリの開いた Pull Request の枝の名前。
export function stuck(config, tasks, running, openBranches) {
  const working = config.transitions.find((t) => t.on === "振り出し").to[0];
  const review = config.coordinator.order[0];
  return tasks
    .filter((t) => (t.status === working && !running.has(t.number) && !t.openChildren.length) || (t.status === review && !openBranches.has(`${config.code.branchPrefix}${t.number}`)))
    .map((t) => ({ number: t.number, reason: t.status === working ? `${working}なのに、担当が動いていない` : `${review}なのに、開いた Pull Request が無い` }))
    .sort((a, b) => a.number - b.number);
}

const clock = (iso) =>
  new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
    .format(new Date(iso))
    .replace(/\//g, "-");

// 状況の更新の中身。stuck が1件でもあれば At risk。時刻の経過では変わらない中身にする（変わったときだけ書き換えるため）。
// runs は動いている担当の実行（{ number, title, url, startedAt }）、started はこの周で起こした仕事（pick の結果。実行の一覧に出るのは次の周から）、
// stop は止めの印の付いた issue の番号、pause は止める時刻。
export function summary(config, { watcher, runs, started, waiting, held, stuck, stop, pause }) {
  const { parallel, stopLabel } = config.coordinator;
  const lines = [`振り出しの見回り（[実行](${watcher})）が書く。中身が変わったときだけ書き換える。`, "", "### 止まっているもの"];
  lines.push(...(stuck.length ? stuck.map((s) => `- #${s.number} ${s.reason}`) : ["無し"]));
  lines.push("", `### 動いている担当（${runs.length + started.length}/${parallel}）`);
  const rows = [
    ...runs.map((r) => `- #${r.number} ${r.title.replace(/^#\d+ /, "")}（${clock(r.startedAt)} から）[実行](${r.url})`),
    ...started.map((t) => `- #${t.number} ${t.kind}（いま起こした）`),
  ];
  lines.push(...(rows.length ? rows : ["無し"]));
  lines.push("", "### 振り出し", `- 振り出しを待つ仕事: ${waiting}件（ほかに前提・段階・開発機を待つもの ${held}件）`);
  if (stop) lines.push(`- 止めている: #${stop} にラベル「${stopLabel}」が付いている`);
  if (pause) lines.push(`- 止めている: ${clock(pause)} まで（利用の上限など）`);
  return { status: stuck.length ? "AT_RISK" : "ON_TRACK", body: lines.join("\n") };
}

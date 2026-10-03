// 振り出しの見回り（bin/dispatch.js）の1周の判断。GitHub から読んだものを受け取り、何を起こすかと状況の更新の中身を決める。
import { openBlockers, waitsUntil } from "./rules.js";

const BOARD = `query Board($o: String!, $n: Int!, $field: String!, $p: String!, $s: String!, $c: String) { organization(login: $o) { projectV2(number: $n) {
  field(name: $p) { ... on ProjectV2SingleSelectField { options { name } } }
  items(first: 100, after: $c, query: "is:open") { pageInfo { hasNextPage endCursor } nodes {
    fieldValueByName(name: $field) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    priority: fieldValueByName(name: $p) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    start: fieldValueByName(name: $s) { ... on ProjectV2ItemFieldDateValue { date } }
    content { ... on Issue { number title url updatedAt labels(first: 20) { nodes { name } }
      blockedBy(first: 50) { nodes { number state stateReason } } } } } } } } }`;

// Project の開いたタスクを全部読む。閉じた項目は読まない（query の is:open。ページ数が閉じた項目の数で増えないように）。
// ranks は優先度の欄の選択肢の並び。startOn は着手可能日（YYYY-MM-DD。無ければ null。Project に欄が無くても null）。
// updatedAt は issue の最後の更新（本文・コメント・ラベル・担当者等。Project の欄の変更は含まない）。
export async function readBoard(gh, config) {
  const items = [];
  let ranks = [];
  for (let c = null; ; ) {
    const d = await gh.gql(BOARD, { o: config.project.owner, n: config.project.number, field: config.project.statusField, p: config.project.priorityField, s: config.project.startField, c });
    const project = d.organization.projectV2;
    ranks = project.field?.options.map((o) => o.name) ?? [];
    items.push(...project.items.nodes);
    if (!project.items.pageInfo.hasNextPage) break;
    c = project.items.pageInfo.endCursor;
  }
  const tasks = items
    .map((i) => ({ ...i.content, status: i.fieldValueByName?.name, priority: i.priority?.name ?? null, startOn: i.start?.date ?? null }))
    .filter((t) => t.number)
    .map((t) => ({
      number: t.number,
      status: t.status,
      title: t.title,
      url: t.url,
      updatedAt: t.updatedAt,
      labels: t.labels.nodes.map((l) => l.name),
      urgent: t.labels.nodes.some((l) => l.name === config.project.urgentLabel),
      priority: t.priority,
      startOn: t.startOn,
      waitingFor: openBlockers(t.blockedBy.nodes).map((b) => b.number),
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

// 担当の種類はステータスで決まる（未着手は作る、検証中は確かめる）。
export const kindOf = (config, status) => (status === config.todo ? "作る" : "確かめる");

// 作り始めの条件で飛ばす未着手: 前提が開いたまま（段階に分けた親も段階に blocked by されてここで待つ）・開発機で扱うタスク
// （ラベル coordinator.devLabel）・着手可能日を待つもの。検証中は飛ばさない（Pull Request を出したものはいつでも確かめに回す）。
const held = (config, t, now) =>
  t.status === config.todo && (t.waitingFor.length > 0 || t.labels.includes(config.coordinator.devLabel) || Boolean(waitsUntil(t.startOn, now)));

// 着手可能日が今日（日本時間）より先で、その日を待っている未着手（動いている番号は除く）。
export const dated = (config, queue, running, now = new Date()) =>
  queue.filter((t) => t.status === config.todo && !running.has(t.number) && waitsUntil(t.startOn, now));

// 枠が空けば振り出せるもの。running は担当のワークフローで動いている（待っているものを含む）issue の番号。
export const ready = (config, queue, running, now = new Date()) => queue.filter((t) => !running.has(t.number) && !held(config, t, now));

// 種類ごとの空いた枠の数。runs は動いている担当の実行（{ number, kind }）。
export const free = (config, runs) =>
  Object.fromEntries(Object.entries(config.coordinator.parallel).map(([kind, n]) => [kind, Math.max(0, n - runs.filter((r) => r.kind === kind).length)]));

// 振り出す仕事を、種類ごとに空いた枠の数だけキューの上から選ぶ（ほかの種類の枠は使わない）。
export function pick(config, queue, runs, now = new Date()) {
  const left = free(config, runs);
  return ready(config, queue, new Set(runs.map((r) => r.number)), now)
    .map((t) => ({ number: t.number, status: t.status, kind: kindOf(config, t.status) }))
    .filter((t) => left[t.kind]-- > 0);
}

// 担当のワークフローの実行の名前（run-name）は「#<番号> <種類>」。名前から番号を読む。
export const runIssue = (title) => Number(/^#(\d+) /.exec(title ?? "")?.[1]) || null;

// 止まっているもの（どれかがあれば At risk）。
// - 長く動いていないタスク: 進行中・検証中のまま、最後の更新から担当の持ち時間（timeoutMinutes）を超えたもの。誰が進めているかは
//   見ない（どの担当の1回も持ち時間より長くは続かない）。着手可能日を待つものは除く。
// - 空いた枠: 止めている（stop・pause）間に、振り出せる仕事がある種類の空いた枠（waiting は振り出せるのに起こしていない仕事、left は空いた枠）。
// - 落ちた実行: failed（前の周の後に失敗で終わった担当の実行。{ number, kind, url }）。
export function stuck(config, { tasks, timeoutMinutes, waiting, left, failed, stop, pause, now = new Date() }) {
  const { working, review } = config;
  const stale = tasks
    .filter((t) => [working, review].includes(t.status) && now - Date.parse(t.updatedAt) > timeoutMinutes * 60000 && !waitsUntil(t.startOn, now))
    .sort((a, b) => a.number - b.number)
    .map((t) => `#${t.number} ${t.status}のまま、${timeoutMinutes}分を超えて動きが無い（最後の動き ${clock(t.updatedAt)}）`);
  const why = stop ? "見回りのワークフローが無効" : `${clock(pause)} まで止めている`;
  const idle = !(stop || pause) ? [] : Object.entries(left)
    .map(([kind, n]) => [kind, n, waiting.filter((t) => kindOf(config, t.status) === kind).length])
    .filter(([, n, w]) => n > 0 && w > 0)
    .map(([kind, n, w]) => `${kind}担当の枠が${n}つ空いているのに、振り出せる仕事${w}件を起こしていない（${why}）`);
  const fell = failed.toSorted((a, b) => a.number - b.number).map((r) => `#${r.number} ${r.kind}担当の実行が失敗で終わった [実行](${r.url})`);
  return [...stale, ...idle, ...fell];
}

const clock = (iso) =>
  new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
    .format(new Date(iso))
    .replace(/\//g, "-");

// 状況の更新の中身。stuck（止まっているものの行）が1件でもあれば At risk。時刻の経過では変わらない中身にする（変わったときだけ書き換えるため）。
// runs は動いている担当の実行（{ number, kind, url, startedAt }）、started はこの周で起こした仕事（pick の結果。実行の一覧に出るのは次の周から）、
// waiting は振り出せるのに起こしていない仕事、held はほかに前提・段階・開発機を待つ数、dated は着手可能日を待つ仕事の着手可能日の並び、
// stop は見回りのワークフローが無効か、pause は止める時刻。
export function summary(config, { watcher, runs, started, waiting, held, dated, stuck, stop, pause }) {
  const kinds = Object.keys(config.coordinator.parallel);
  const count = (list, kind) => list.filter((x) => x.kind === kind).length;
  const lines = [`振り出しの見回り（[実行](${watcher})）が書く。中身が変わったときだけ書き換える。`, "", "### 止まっているもの"];
  lines.push(...(stuck.length ? stuck.map((s) => `- ${s}`) : ["無し"]));
  lines.push("", `### 動いている担当（${kinds.map((k) => `${k} ${count(runs, k) + count(started, k)}/${config.coordinator.parallel[k]}`).join("・")}）`);
  const rows = [
    ...runs.map((r) => `- #${r.number} ${r.kind}（${clock(r.startedAt)} から）[実行](${r.url})`),
    ...started.map((t) => `- #${t.number} ${t.kind}（いま起こした）`),
  ];
  lines.push(...(rows.length ? rows : ["無し"]));
  const by = kinds.map((k) => `${k} ${waiting.filter((t) => kindOf(config, t.status) === k).length}件`).join("・");
  lines.push("", "### 振り出し", `- 振り出しを待つ仕事: ${by}（ほかに前提・段階・開発機を待つもの ${held}件）`);
  if (dated.length) lines.push(`- 着手可能日を待つ仕事: ${dated.length}件（最も近い日 ${dated.toSorted()[0]}）`);
  if (stop) lines.push("- 止めている: 見回りのワークフローが無効（Actions の画面で Enable workflow のあと Run workflow で戻す）");
  if (pause) lines.push(`- 止めている: ${clock(pause)} まで（利用の上限など）`);
  return { status: stuck.length ? "AT_RISK" : "ON_TRACK", body: lines.join("\n") };
}

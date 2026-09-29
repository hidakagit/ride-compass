// Claude が振り出すタスク（ステータスが coordinator.order のもの。誰の番かはステータスで決まる）を、振り出す順に並べて出す。
// 並び: ステータスの順（coordinator.order）→ ラベル「急ぎ」（project.urgentLabel。
// ユーザーの依頼で、優先度の欄より上）→ Project の優先度の欄の選択肢の順（欄に選択肢を足せば、そのまま並びに効く。
// 値の無いものは最後）→ 番号の若い順。前提が開いたままの未着手には印を付ける。
// 使い方: node tools/flow-gate/bin/queue.js [--json]
import config from "../flow.config.json" with { type: "json" };
import { GitHub } from "../src/github.js";
import { openBlockers } from "../src/rules.js";
import { botToken } from "./token.js";

if (process.argv.slice(2).some((a) => a !== "--json")) {
  console.error("使い方: node tools/flow-gate/bin/queue.js [--json]");
  process.exit(2);
}
const ORDER = config.coordinator.order;
const gh = new GitHub(botToken());
const q = `query Queue($o: String!, $n: Int!, $field: String!, $p: String!, $c: String) { organization(login: $o) { projectV2(number: $n) {
  field(name: $p) { ... on ProjectV2SingleSelectField { options { name } } }
  items(first: 100, after: $c) { pageInfo { hasNextPage endCursor } nodes {
    fieldValueByName(name: $field) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    priority: fieldValueByName(name: $p) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    content { ... on Issue { number title url state labels(first: 20) { nodes { name } }
      blockedBy(first: 50) { nodes { number state stateReason } } } } } } } } }`;
const items = [];
let ranks = [];
for (let c = null; ; ) {
  const d = await gh.gql(q, { o: config.project.owner, n: config.project.number, field: config.project.statusField, p: config.project.priorityField, c });
  const project = d.organization.projectV2;
  ranks = project.field?.options.map((o) => o.name) ?? [];
  items.push(...project.items.nodes);
  if (!project.items.pageInfo.hasNextPage) break;
  c = project.items.pageInfo.endCursor;
}
const rank = (p) => (ranks.includes(p) ? ranks.indexOf(p) : ranks.length);
const tasks = items
  .map((i) => ({ ...i.content, status: i.fieldValueByName?.name, priority: i.priority?.name ?? null }))
  .filter((t) => t.number && t.state === "OPEN" && ORDER.includes(t.status))
  .map((t) => ({
    number: t.number,
    status: t.status,
    title: t.title,
    url: t.url,
    urgent: t.labels.nodes.some((l) => l.name === config.project.urgentLabel),
    priority: t.priority,
    waitingFor: openBlockers(t.blockedBy.nodes).map((b) => b.number),
  }))
  .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || b.urgent - a.urgent || rank(a.priority) - rank(b.priority) || a.number - b.number);

if (process.argv.includes("--json")) console.log(JSON.stringify(tasks, null, 2));
else if (!tasks.length) console.log("振り出すタスクは無い");
else
  for (const t of tasks)
    console.log(
      `#${t.number} ${t.status}${t.urgent ? ` ${config.project.urgentLabel}` : ""}${t.priority ? ` ${config.project.priorityField}:${t.priority}` : ""}` +
        `${t.waitingFor.length ? ` 前提待ち（${t.waitingFor.map((n) => `#${n}`).join("・")}）` : ""} ${t.title}`,
    );

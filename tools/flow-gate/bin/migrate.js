// 1回だけ打つ移行の道具: ステータスをゲートが事実から決める形へ移す。札「開発機が要る」の付いた開いたタスクは、対話作業の段階を起こして
// 前提に張り（何が要るかは札を付けたときのコメントにある）、札を外す。そのあと Actions のボードの開いたタスクを全部、ゲートに決め直させる
// （置き場への repository_dispatch「recheck」）。ゲートを公開し、GitHub の設定を済ませてから打つ（docs/conventions/flow.md「ゲートを変える・公開する」）。
import { createStage, readTask } from "../src/github.js";
import { readTasks } from "../src/dispatch.js";
import { args, bot, config } from "./cli.js";

const LABEL = "開発機が要る";
const { dry } = args("node tools/flow-gate/bin/migrate.js [--dry-run]", (a) => !a.length);
const say = (line) => console.log(`${dry ? "（試し）" : ""}${line}`);
const gh = bot();
const { tasks } = await readTasks(gh, config, "is:open");
for (const t of tasks) {
  const { issue, labels } = await readTask(gh, config, { number: t.number });
  if (!issue.labels.nodes.some((l) => l.name === LABEL)) continue;
  say(`#${t.number} の札「${LABEL}」を、対話作業の段階と前提に移す`);
  if (dry) continue;
  const body = `札「${LABEL}」から移した、開発機の対話のセッションがする作業。何が要るかは親 #${t.number} の、札を付けたときのコメントにある。\n\n` +
    `<details><summary>完了の条件</summary>\n\n- [ ] 親 #${t.number} で開発機が要るとした作業が済んでいる\n</details>\n`;
  const stage = await createStage(gh, config, issue, { title: `開発機で: ${issue.title}`.slice(0, 120), body, dialog: true });
  await gh.write([["removeLabelsFromLabelable", { labelableId: issue.id, labelIds: [labels[LABEL]] }]]);
  say(`#${t.number} に対話作業の段階 #${stage.number} を張った`);
}
for (const t of tasks) {
  say(`#${t.number}（${t.status ?? "ステータス無し"}）をゲートに決め直させる`);
  if (!dry) await gh.rest("POST", `/repos/${config.repository}/dispatches`, { event_type: "recheck", client_payload: { number: t.number } });
}

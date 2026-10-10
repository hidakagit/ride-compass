// 移行の道具: ステータスをゲートが事実から決める形へ移す。何度打っても同じ結果になる。
// 1. 準備（src/prepare.js: prepare）: コードが前提にする GitHub の設定（ボードの選択肢・対話作業のボード・issue の種類）を、無ければ作り、
//    読み直して確かめる。足りないもの（API で変えられないゲートの App の権限と出来事等）があれば、直し方を出して移行せずに 1 で終える。
// 2. 札「開発機が要る」の付いた開いたタスクは、対話作業の段階を起こして前提に張り（何が要るかは札を付けたときのコメントにある）、札を外す。
// 3. Actions のボードの開いたタスクを全部、ゲートに決め直させる（置き場への repository_dispatch「recheck」）。
// ゲートを公開してから打つ（docs/conventions/flow.md「ゲートを変える・公開する」）。
import { createStage, readTask } from "../src/github.js";
import { readTasks } from "../src/dispatch.js";
import { prepare } from "../src/prepare.js";
import { args, bot, config } from "./cli.js";

const LABEL = "開発機が要る";
const { dry } = args("node tools/flow-gate/bin/migrate.js [--dry-run]", (a) => !a.length);
const say = (line) => console.log(`${dry ? "（試し）" : ""}${line}`);
const gh = bot();
const problems = await prepare(gh, config, { dry, say });
for (const p of problems) console.log(`足りない: ${p}`);
if (problems.length && !dry) process.exit(1);
say(problems.length ? "準備に足りないものがある（試しなので続けて見せる）" : "準備は済んでいる（設定とコードの名前・番号が一致する）");
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

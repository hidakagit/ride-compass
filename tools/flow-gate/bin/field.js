// Claude が Project の欄（優先度・着手可能日）を書く。優先度は、入っていれば誰かが決めた値（ユーザーが付けた・起票で
// 見積もった）なので、別の値へは書き換えない。起票の直後の issue は Project に入るまで待つ（入れるのは GitHub の
// 組み込みの自動化で、入るまでに間がある）。値を渡さなければ書かずに、Project の欄（Status を含む）の今の値を出す（空の欄は null）。
import { readTask, setField } from "../src/github.js";
import { args, bot, config, isNumber } from "./cli.js";

const { rest: [number, name, value] } = args("node tools/flow-gate/bin/field.js <issue の番号> [<欄の名前> <選択肢の名前 | YYYY-MM-DD | 消す>]（Status は move.js で動かす）",
  (a) => isNumber(a[0]) && (a.length === 1 || (a.length === 3 && a[1] !== config.project.statusField)));
const gh = bot();
let task = await readTask(gh, config, { number: Number(number) });
for (let k = 0; !task.issue?.item && k < 12; k++) {
  if (!k) console.error(`#${number} はまだ ${config.repository} の Project に入っていないので、入るまで待つ（最長2分）`);
  await new Promise((r) => setTimeout(r, 10e3));
  task = await readTask(gh, config, { number: Number(number) });
}
const { project, issue } = task;
if (!issue?.item) throw new Error(`#${number} は ${config.repository} の Project の件ではありません。`);
if (name === undefined) {
  console.log(JSON.stringify(Object.fromEntries(Object.keys(project.fields).map((f) => [f, issue.fields[f] ?? null]))));
  process.exit(0);
}
const now = issue.fields[name];
if (name === config.project.priorityField && now && now !== value) throw new Error(`#${number}: 欄「${name}」の今の値「${now}」は決めてある値なので書き換えません。変えるならユーザーに問います。`);
await gh.write([setField(project, issue.item, name, value === "消す" ? null : value)]);
console.log(`#${number}: ${name} ${now ?? "無し"} → ${value}`);

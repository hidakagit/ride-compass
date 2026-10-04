// Claude が Project の欄（規模・優先度・着手可能日）を書く。既定（flow.config.json: project.defaults）を持つ欄で、今の値が既定と
// 違えば、誰かが決めた値（ユーザーが付けた・起票で見積もった・親から継いだ）なので、別の値へは書き換えない。
// 値を渡さなければ書かずに、Project の欄（Status を含む）の今の値を出す（空の欄は null）。
import { readTask, setField } from "../src/github.js";
import { args, bot, config, isNumber } from "./cli.js";

const { rest: [number, name, value] } = args("node tools/flow-gate/bin/field.js <issue の番号> [<欄の名前> <選択肢の名前 | YYYY-MM-DD | 消す>]（Status は move.js で動かす）",
  (a) => isNumber(a[0]) && (a.length === 1 || (a.length === 3 && a[1] !== config.project.statusField)));
const gh = bot();
const { project, issue } = await readTask(gh, config, { number: Number(number) });
if (!issue?.item) throw new Error(`#${number} は ${config.repository} の Project の件ではありません。`);
if (name === undefined) {
  console.log(JSON.stringify(Object.fromEntries(Object.keys(project.fields).map((f) => [f, issue.fields[f] ?? null]))));
  process.exit(0);
}
const now = issue.fields[name];
const fallback = config.project.defaults[name];
if (fallback && now && now !== fallback && now !== value) throw new Error(`#${number}: 欄「${name}」の今の値「${now}」は既定（${fallback}）と違う、決めてある値なので書き換えません。変えるならユーザーに問います。`);
await gh.write([setField(project, issue.item, name, value === "消す" ? null : value)]);
console.log(`#${number}: ${name} ${now ?? "無し"} → ${value}`);

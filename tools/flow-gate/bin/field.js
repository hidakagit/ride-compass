// Claude がタスクの Project の欄（規模・優先度などの単一選択と、着手可能日の日付。Status は move.js）を名前で書く（hidakagit-bot の名義）。
// 既定と違う値（決めてある値）は書き換えない（src/rules.js: fieldRefusal）。日付の欄は「消す」で値を消す。
// 使い方: node tools/flow-gate/bin/field.js <issue の番号> <欄の名前> <選択肢の名前 | YYYY-MM-DD | 消す>
import config from "../flow.config.json" with { type: "json" };
import { GitHub, Mutations, readTask, setField } from "../src/github.js";
import { fieldRefusal } from "../src/rules.js";
import { botToken } from "./token.js";

const args = process.argv.slice(2);
const [number, name, given] = args;
if (args.length !== 3 || !/^\d+$/.test(number) || name === config.project.statusField) {
  console.error("使い方: node tools/flow-gate/bin/field.js <issue の番号> <欄の名前> <選択肢の名前 | YYYY-MM-DD | 消す>（Status は move.js で動かす）");
  process.exit(2);
}
const gh = new GitHub(botToken());
const { project, issue } = await readTask(gh, config, { number: Number(number) });
if (!issue?.item) throw new Error(`#${number} は ${config.repository} の Project の件ではありません。`);
const value = project.fields[name]?.date && given === "消す" ? null : given;
const refusal = fieldRefusal(config, name, issue.fields[name], value);
if (refusal) throw new Error(`#${number}: ${refusal}`);
await setField(new Mutations(), project, issue.item, name, value).send(gh);
console.log(`#${number}: ${name} ${issue.fields[name] ?? "無し"} → ${value ?? "無し"}`);

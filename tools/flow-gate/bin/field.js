// Claude がタスクの Project の単一選択の欄（規模・優先度など。Status は move.js）を名前で書く（hidakagit-bot の名義）。
// 使い方: node tools/flow-gate/bin/field.js <issue の番号> <欄の名前> <選択肢の名前>
import config from "../flow.config.json" with { type: "json" };
import { GitHub, readTask } from "../src/github.js";
import { botToken } from "./token.js";

const [number, name, value] = process.argv.slice(2);
if (!/^\d+$/.test(number ?? "") || !name || !value || name === config.project.statusField) {
  console.error("使い方: node tools/flow-gate/bin/field.js <issue の番号> <欄の名前> <選択肢の名前>（Status は move.js で動かす）");
  process.exit(2);
}
const gh = new GitHub(botToken());
const { project, issue } = await readTask(gh, config, { number: Number(number) });
if (!issue?.item) throw new Error(`#${number} は ${config.repository} の Project の件ではありません。`);
const field = project.fields[name];
if (!field) throw new Error(`欄「${name}」が Project にありません（${Object.keys(project.fields).join("・")}）。`);
if (!field.options[value]) throw new Error(`欄「${name}」に選択肢「${value}」がありません（${field.order.join("・")}）。`);
await gh.gql(
  `mutation Set($p: ID!, $i: ID!, $f: ID!, $o: String!) { updateProjectV2ItemFieldValue(input: { projectId: $p, itemId: $i, fieldId: $f, value: { singleSelectOptionId: $o } }) { clientMutationId } }`,
  { p: project.id, i: issue.item, f: field.id, o: field.options[value] },
);
console.log(`#${number}: ${name} ${issue.fields[name] ?? "無し"} → ${value}`);

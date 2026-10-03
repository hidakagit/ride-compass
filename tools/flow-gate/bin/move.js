// Claude がステータスを動かす（hidakagit-bot の名義）。行き先を、ほかの経路と同じ照らし（src/rules.js: judge）で見て、通れば書く。
// 理由を渡すと、理由をコメントに書いてから動かす。問いを置いて回答待ちにするのは ask.js。
// 使い方: node tools/flow-gate/bin/move.js [--dry-run] <issue の番号> <行き先のステータス> [理由]
// （--dry-run は今の状態で遷移を照らして行き先を出すだけで、書かない）
import config from "../flow.config.json" with { type: "json" };
import { GitHub, Mutations, readTask, setField } from "../src/github.js";
import { judge } from "../src/rules.js";
import { botToken } from "./token.js";

const dry = process.argv[2] === "--dry-run";
const args = process.argv.slice(dry ? 3 : 2);
const [number, to, reason] = args;
if (!/^\d+$/.test(number ?? "") || !config.statuses.includes(to) || args.length > 3 || (args.length === 3 && !reason.trim())) {
  console.error(`使い方: node tools/flow-gate/bin/move.js [--dry-run] <issue の番号> <${config.statuses.join("|")}> [理由]`);
  process.exit(2);
}

const gh = new GitHub(botToken());
const { project, issue } = await readTask(gh, config, { number: Number(number) });
if (!issue?.item || issue.state !== "OPEN") throw new Error(`#${number} は ${config.repository} の Project の開いた件ではありません。`);
const verdict = judge(config, issue.status, to, { close: to === config.done ? "COMPLETED" : undefined, issue });
if (!verdict.ok) throw new Error(verdict.reason);
if (dry) {
  console.log(`（試し）#${number}: ${issue.status} → ${to}`);
  process.exit(0);
}
const m = new Mutations();
if (reason) m.add("addComment", { subjectId: issue.id, body: `${to}にする理由: ${reason.trim()}` });
await setField(m, project, issue.item, config.project.statusField, to).send(gh);
console.log(`#${number}: ${issue.status} → ${to}`);

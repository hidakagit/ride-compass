// Claude の出来事でステータスを動かす（hidakagit-bot の名義）。動かせるのは遷移の表で Claude が起こす出来事（by: claude）だけで、
// 問いは ask.js が起こす。理由が要る出来事（reason）は、理由をコメントに書いてから動かす。
// 使い方: node tools/flow-gate/bin/move.js [--dry-run] <issue の番号> <出来事>（理由が要る出来事なら続けて <理由>）
// （--dry-run は今の状態で遷移を照らして行き先を出すだけで、書かない）
import config from "../flow.config.json" with { type: "json" };
import { GitHub, Mutations, readTask, setField } from "../src/github.js";
import { check } from "../src/rules.js";
import { botToken } from "./token.js";

const events = config.transitions.filter((t) => t.by === "claude" && t.on !== "問い");
const dry = process.argv[2] === "--dry-run";
const args = process.argv.slice(dry ? 3 : 2);
const [number, on, reason] = args;
const event = events.find((t) => t.on === on);
if (!/^\d+$/.test(number ?? "") || !event || args.length !== (event.reason ? 3 : 2) || (event.reason && !reason.trim())) {
  console.error(`使い方: node tools/flow-gate/bin/move.js [--dry-run] <issue の番号> <${events.map((t) => t.on).join("|")}>（${events.filter((t) => t.reason).map((t) => t.on).join("・")}なら続けて <理由>）`);
  process.exit(2);
}
const gh = new GitHub(botToken());
const { project, issue } = await readTask(gh, config, { number: Number(number) });
if (!issue?.item || issue.state !== "OPEN") throw new Error(`#${number} は ${config.repository} の Project の開いた件ではありません。`);
const to = event.to[0];
const verdict = check(config, issue.status, to, { on, by: "claude", blockers: issue.blockedBy.nodes });
if (!verdict.ok) throw new Error(verdict.reason);
if (dry) {
  console.log(`（試し）#${number}: ${on} ${issue.status} → ${to}`);
  process.exit(0);
}
const m = new Mutations();
if (event.reason) m.add("addComment", { subjectId: issue.id, body: `${on}（${to}にする理由）: ${reason.trim()}` });
await setField(m, project, issue.item, config.project.statusField, to).send(gh);
console.log(`#${number}: ${on} ${issue.status} → ${to}`);

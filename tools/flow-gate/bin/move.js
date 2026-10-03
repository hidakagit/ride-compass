// Claude がステータスを動かす（hidakagit-bot の名義。src/move.js: moveTask）。問いを置いて回答待ちにするのは ask.js。
// 使い方: node tools/flow-gate/bin/move.js [--dry-run] <issue の番号> <行き先のステータス> [理由]
// （--dry-run は今の状態で遷移を照らして行き先を出すだけで、書かない）
import config from "../flow.config.json" with { type: "json" };
import { GitHub } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { botToken } from "./token.js";

const dry = process.argv[2] === "--dry-run";
const args = process.argv.slice(dry ? 3 : 2);
const [number, to, reason] = args;
if (!/^\d+$/.test(number ?? "") || !config.statuses.includes(to) || args.length > 3 || (args.length === 3 && !reason.trim())) {
  console.error(`使い方: node tools/flow-gate/bin/move.js [--dry-run] <issue の番号> <${config.statuses.join("|")}> [理由]`);
  process.exit(2);
}
console.log(await moveTask(new GitHub(botToken()), config, Number(number), to, reason, { dry }));

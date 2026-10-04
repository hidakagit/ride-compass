// Claude がステータスを動かす（src/move.js: moveTask）。理由を渡すと、理由をコメントに書いてから動かす。
import { moveTask } from "../src/move.js";
import { args, bot, config, isNumber } from "./cli.js";

const { dry, rest: [number, to, reason] } = args(`node tools/flow-gate/bin/move.js [--dry-run] <issue の番号> <${config.statuses.join("|")}> [理由]`,
  (a) => isNumber(a[0]) && config.statuses.includes(a[1]) && a.length <= 3 && (a.length < 3 || a[2].trim()));
console.log(await moveTask(bot(), config, Number(number), to, { comment: reason && `${to}にする理由: ${reason.trim()}`, dryRun: dry }));

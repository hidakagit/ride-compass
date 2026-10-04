// Claude がユーザーに問う。問いの形（docs/conventions/flow.md「問い」）を確かめてコメントに書き、回答待ちへ動かす。もう回答待ちなら
// 動かさずにコメントだけを書く（問い直し。今の問いは最新の「## 問い」のコメント）。
import { readFileSync } from "node:fs";
import { readTask } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { normalize, parseQuestion } from "../src/rules.js";
import { args, bot, config, isNumber } from "./cli.js";

const { rest: [number, file] } = args("node tools/flow-gate/bin/ask.js <issue の番号> <問いのファイル>", (a) => a.length === 2 && isNumber(a[0]));
const question = normalize(readFileSync(file, "utf8")).trim();
if (!parseQuestion(question)) throw new Error("問いが形（docs/conventions/flow.md「問い」）に合いません。");
const gh = bot();
const { issue } = await readTask(gh, config, { number: Number(number) });
if (issue?.state === "OPEN" && issue.status === config.waiting) {
  await gh.write([["addComment", { subjectId: issue.id, body: question }]]);
  console.log(`#${number}: 回答待ちのまま問い直した`);
} else console.log(await moveTask(gh, config, Number(number), config.waiting, { comment: question }));

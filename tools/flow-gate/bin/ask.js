// Claude がユーザーに問う。問いの形（docs/conventions/flow.md「問い」）を確かめて、src/move.js: askTask で書く。
import { readFileSync } from "node:fs";
import { askTask } from "../src/move.js";
import { normalize, parseQuestion } from "../src/rules.js";
import { args, bot, config, isNumber } from "./cli.js";

const { rest: [number, file] } = args("node tools/flow-gate/bin/ask.js <issue の番号> <問いのファイル>", (a) => a.length === 2 && isNumber(a[0]));
const question = normalize(readFileSync(file, "utf8")).trim();
if (!parseQuestion(question)) throw new Error("問いが形（docs/conventions/flow.md「問い」）に合いません。");
console.log(await askTask(bot(), config, Number(number), question));

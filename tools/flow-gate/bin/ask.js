// 担当がユーザーに問う（判断）。形（tools/flow-gate/question_template.md）を照らして、src/ask.js: askTask で書く。
import { readFileSync } from "node:fs";
import { askTask } from "../src/ask.js";
import { normalize } from "../src/rules.js";
import { args, bot, config, isNumber } from "./cli.js";

const { rest: [number, file] } = args("node tools/flow-gate/bin/ask.js <issue の番号> <問いのファイル>", (a) => a.length === 2 && isNumber(a[0]));
console.log(await askTask(bot(), config, Number(number), normalize(readFileSync(file, "utf8")).trim()));

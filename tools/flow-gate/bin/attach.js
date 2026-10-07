// Pull Request へ画像を1枚ずつ貼り、貼れなければ文言で分けて打ち直すか止め、打ち直しを使い切ったら置き場の issue へ貼って
// Pull Request にリンクを書く（flow.md「作る担当」の5の「貼り方」。分け方は src/attach.js）。gh を、コードのリポジトリへは GH_TOKEN、
// 置き場へは FLOW_BOT_TOKEN の名義で打つ。
import { spawnSync } from "node:child_process";
import { attach } from "../src/attach.js";
import { args, bot, code, config, isNumber } from "./cli.js";

const { rest: [pr, issue, ...images] } = args("node tools/flow-gate/bin/attach.js <Pull Request の番号> <issue の番号> <画像>#<見出し>...",
  (a) => isNumber(a[0]) && isNumber(a[1]) && a.length > 2);
const tokens = { code: code().token, bot: bot().token };
const run = (a, as) => spawnSync("gh", a, { encoding: "utf8", env: { ...process.env, GH_TOKEN: tokens[as] } });
const sleep = (s) => new Promise((r) => setTimeout(r, s * 1e3));
for (const line of await attach({ run, sleep, code: config.code.repository, tasks: config.repository, pr, issue, images })) console.log(line);

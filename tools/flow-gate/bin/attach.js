// Pull Request へ画像を1枚ずつ貼り、貼れなければ止まる（flow.md「作る担当」の5の「貼り方」。src/attach.js）。gh をコードのリポジトリの
// 名義（GH_TOKEN）で打つ。
import { spawnSync } from "node:child_process";
import { attach } from "../src/attach.js";
import { args, code, config, isNumber } from "./cli.js";

const { rest: [pr, ...images] } = args("node tools/flow-gate/bin/attach.js <Pull Request の番号> <画像>#<見出し>...",
  (a) => isNumber(a[0]) && a.length > 1 && a.slice(1).every((i) => i.includes("#")));
const token = code().token;
const run = (a) => spawnSync("gh", a, { encoding: "utf8", env: { ...process.env, GH_TOKEN: token } });
for (const line of attach({ run, code: config.code.repository, pr, images })) console.log(line);

// 開発機の対話のセッションがタスクを触る前に、そのタスクの担当のワークフローのグループ（.github/workflows/claude-task.yml の
// concurrency）を持つ。種類「開発機」の実行が動き始めたら実行の URL を出して 0 で終え、もう動いている種類「開発機」の実行が
// あるか、持つ実行が動かずに終わったら 1 で終える（src/hold.js: hold）。触り終えたら --release <実行の id> で、持った実行の
// 取り消しを頼み、受け付けられたら止まるのを待たずに 0、受け付けられなければその応答を出して 1 で終える（src/hold.js: release）。
// 開発機でログイン済みの gh（hidakagit）のトークンで打つ。
import { execFileSync } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { GitHub } from "../src/github.js";
import { hold, release } from "../src/hold.js";
import { args, config, isNumber } from "./cli.js";

const { rest: [number, off, id] } = args("node tools/flow-gate/bin/hold.js <issue の番号> [--release <実行の id>]",
  (a) => isNumber(a[0]) && (a.length === 1 || (a.length === 3 && a[1] === "--release" && isNumber(a[2]))));
const gh = new GitHub(execFileSync("gh", ["auth", "token"], { encoding: "utf8" }).trim());

const wait = () => sleep(10e3);
const releaseCommand = (r) => `node tools/flow-gate/bin/hold.js ${number} --release ${r.id}`;

if (off) {
  const run = await release(gh, config, number, id).catch((e) => {
    console.log(`#${number} を手放せなかった: ${e.message}`);
    process.exit(1);
  });
  console.log(run.status === "completed"
    ? `#${number} を手放した（実行はもう ${run.conclusion} で終わっていた）: ${run.html_url}`
    : `#${number} を手放した（実行の取り消しを頼んだ。止まりきるまでの間、見回りはこのタスクを振り出さない）: ${run.html_url}`);
  process.exit(0);
}
// 動いている実行があれば、列に並ばずに終える（並ぶと、その実行が手放されるまで最大6時間待つ）。
const { held, mine } = await hold(gh, config, number, wait);
if (held) {
  console.log(`#${number} はもう種類「開発機」の実行が持っている: ${held.html_url}（自分が持ったものなら、持ち直さずに続け、${releaseCommand(held)} で手放す。別のセッションのものなら、手放されてから打ち直す）`);
  process.exit(1);
}
if (mine.status === "in_progress") {
  console.log(`#${number} を持った: ${mine.html_url}（手放すときは ${releaseCommand(mine)}）`);
  process.exit(0);
}
console.log(`#${number} を持てなかった（実行が ${mine.conclusion} で終わった）: ${mine.html_url}`);
process.exit(1);

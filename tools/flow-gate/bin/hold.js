// 開発機の対話のセッションがタスクを触る前に、そのタスクの担当のワークフローのグループ（.github/workflows/claude-task.yml の
// concurrency）を持つ。種類「開発機」の実行を起こし、前の実行が終わって動き始めたら実行の URL を出して 0 で終える。取り消されたか、
// 起こした実行が FIND_MINUTES のうちに終わっていない実行の一覧に出なければ 1 で終える。触り終えたら --release で、その番号の
// 種類「開発機」の終わっていない実行を取り消して手放す。
// 開発機でログイン済みの gh（hidakagit）で打つ。
import { execFileSync } from "node:child_process";
import { readActive, runOf } from "../src/dispatch.js";
import { args, config, isNumber } from "./cli.js";

const FIND_MINUTES = 10;
const { rest: [number, release] } = args("node tools/flow-gate/bin/hold.js <issue の番号> [--release]",
  (a) => isNumber(a[0]) && (a.length === 1 || (a.length === 2 && a[1] === "--release")));
const { repository, base } = config.code;
const gh = (...a) => execFileSync("gh", a, { encoding: "utf8" });
const pick = "{id, status, conclusion, display_title, html_url}";
// 実行の応答は大きいので、gh の側で要る項目だけに絞る。
const holds = async () => (await readActive((path) => JSON.parse(gh("api", path, "--jq", `{workflow_runs: [.workflow_runs[] | ${pick}]}`)), config))
  .filter((r) => { const [n, kind] = runOf(r.display_title); return Number(n) === Number(number) && kind === "開発機"; });

if (release) {
  for (const r of await holds()) gh("api", "-X", "POST", `repos/${repository}/actions/runs/${r.id}/cancel`);
  console.log(`#${number} を手放した`);
  process.exit(0);
}
// もう種類「開発機」の実行が持っていれば、列に並ばずに終える（並ぶと、その実行が手放されるまで最大6時間待つ）。誰の実行かは
// 道具には分からないので、どうするかは打った者が決める。
const held = (await holds())[0];
if (held) {
  console.log(`#${number} はもう種類「開発機」の実行が持っている: ${held.html_url}（自分が持ったものなら、持ち直さずに続ける。別のセッションのものなら、手放されてから打ち直す）`);
  process.exit(1);
}
// 起こした実行は、起こしたあとに終わっていない実行の一覧に出た種類「開発機」の実行（workflow_dispatch は実行の id を返さない）。
// 見つけたら id で追う（一覧から外れても見失わない）。
gh("workflow", "run", config.coordinator.workflow, "-R", repository, "--ref", base, "-f", `issue=${number}`, "-f", "kind=開発機");
const wait = () => new Promise((r) => setTimeout(r, 10e3));
let mine;
for (const until = Date.now() + FIND_MINUTES * 60e3; !mine; ) {
  if (Date.now() > until) {
    console.log(`#${number} を持てなかった（起こした実行が ${FIND_MINUTES}分のうちに終わっていない実行の一覧に出なかった。Actions の画面で claude-task.yml の実行を見る）`);
    process.exit(1);
  }
  await wait();
  mine = (await holds())[0];
}
for (;;) {
  if (mine.status === "in_progress") {
    console.log(`#${number} を持った: ${mine.html_url}`);
    process.exit(0);
  }
  if (mine.status === "completed") {
    console.log(`#${number} を持てなかった（実行が ${mine.conclusion} で終わった）: ${mine.html_url}`);
    process.exit(1);
  }
  await wait();
  mine = JSON.parse(gh("api", `repos/${repository}/actions/runs/${mine.id}`, "--jq", pick));
}

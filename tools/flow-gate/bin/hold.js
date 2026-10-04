// 開発機の対話のセッションがタスクを触る前に、そのタスクの担当のワークフローのグループ（.github/workflows/claude-task.yml の
// concurrency）を持つ。種類「開発機」の実行を起こし、前の実行が終わって動き始めたら実行の URL を出して 0 で終える。取り消されたら
// 1 で終える。触り終えたら --release で、その番号の種類「開発機」の終わっていない実行を取り消して手放す。
// 開発機でログイン済みの gh（hidakagit）で打つ。
import { execFileSync } from "node:child_process";
import { runOf } from "../src/dispatch.js";
import { args, config, isNumber } from "./cli.js";

const { rest: [number, release] } = args("node tools/flow-gate/bin/hold.js <issue の番号> [--release]",
  (a) => isNumber(a[0]) && (a.length === 1 || (a.length === 2 && a[1] === "--release")));
const { workflow } = config.coordinator;
const { repository, base } = config.code;
const gh = (...a) => execFileSync("gh", a, { encoding: "utf8" });
// 実行の一覧は大きいので、gh の側で要る項目だけに絞る。
const holds = () => JSON.parse(gh("api", `repos/${repository}/actions/workflows/${workflow}/runs?per_page=50`, "--jq", "[.workflow_runs[] | {id, status, conclusion, display_title, html_url}]"))
  .filter((r) => { const [n, kind] = runOf(r.display_title); return Number(n) === Number(number) && kind === "開発機"; });

if (release) {
  for (const r of holds().filter((r) => r.status !== "completed")) gh("api", "-X", "POST", `repos/${repository}/actions/runs/${r.id}/cancel`);
  console.log(`#${number} を手放した`);
  process.exit(0);
}
// もう種類「開発機」の実行が持っていれば、列に並ばずに終える（並ぶと、その実行が手放されるまで最大6時間待つ）。誰の実行かは
// 道具には分からないので、どうするかは打った者が決める。
const runs = holds();
const held = runs.find((r) => r.status !== "completed");
if (held) {
  console.log(`#${number} はもう種類「開発機」の実行が持っている: ${held.html_url}（自分が持ったものなら、持ち直さずに続ける。別のセッションのものなら、手放されてから打ち直す）`);
  process.exit(1);
}
// 起こした実行は、起こす前に無かった種類「開発機」の実行のうち一番新しいもの（workflow_dispatch は実行の id を返さない）。
const before = new Set(runs.map((r) => r.id));
gh("workflow", "run", workflow, "-R", repository, "--ref", base, "-f", `issue=${number}`, "-f", "kind=開発機");
for (;;) {
  await new Promise((r) => setTimeout(r, 10e3));
  const mine = holds().find((r) => !before.has(r.id));
  if (mine?.status === "in_progress") {
    console.log(`#${number} を持った: ${mine.html_url}`);
    process.exit(0);
  }
  if (mine?.status === "completed") {
    console.log(`#${number} を持てなかった（実行が ${mine.conclusion} で終わった）: ${mine.html_url}`);
    process.exit(1);
  }
}

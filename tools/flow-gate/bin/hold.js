// 開発機の対話のセッションがタスクを触る前に、そのタスクを持つ印を取る（src/hold.js: take）。持てたら手放す打ち方を出して 0、
// 持てなければ今の持ち主を出して 1 で終える（自分の印は残さない）。触り終えたら --release <合言葉> で手放す（src/hold.js: release）。
// 何度打っても同じ結果で、印が無ければ手放したとして 0、ほかの者の印なら消さずに 1 で終える。Actions の実行は起こさない。
import { devHolder, release, take } from "../src/hold.js";
import { args, config, holds, isNumber } from "./cli.js";

const { rest: [number, off, word] } = args("node tools/flow-gate/bin/hold.js <issue の番号> [--release <合言葉>]",
  (a) => isNumber(a[0]) && (a.length === 1 || (a.length === 3 && a[1] === "--release" && /^\S+$/.test(a[2]))));
const remote = holds();

if (off) {
  const r = await release(remote, config, number, devHolder(word)).catch((e) => ({ error: e.message }));
  if (r.released) console.log(`#${number} を手放した（印はもう無い）`);
  else console.log(r.error ? `#${number} を手放せなかった（${r.error}）。打ち直す` : `#${number} は「${r.by}」が持っているので手放さない`);
  process.exit(r.released ? 0 : 1);
}
const who = devHolder();
const r = await take(remote, config, number, who).catch((e) => ({ held: false, error: e.message }));
if (r.held) {
  console.log(`#${number} を持った（手放すときは node tools/flow-gate/bin/hold.js ${number} --release ${who.split(" ")[1]}）`);
  process.exit(0);
}
console.log(r.error ? `#${number} を持てなかった（${r.error}）`
  : `#${number} を持てなかった（持ち主: ${r.by ?? "読み直せなかった"}）${r.left ? `。自分の印 ${r.left} を消しきれなかったので、node tools/flow-gate/bin/hold.js ${number} --release ${who.split(" ")[1]} を打ち直す` : ""}`);
process.exit(1);

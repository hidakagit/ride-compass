// 必須のチェックが通らなかった実行を見分け、ランナーが付かずに取り消されたものなら、取り消されたジョブとそれに needs で続くジョブだけを
// 流し直す（flow.md「作る担当」の5）。見分けは src/rerun.js: verdict。
// 終わりの値: 0 流し直した（試しなら流し直すはず）・1 落ちた（流し直しに当たらない。直す）・3 流し直しを使い切った（報告して終える）・
// 4 実行が終わっていない（gh run watch で待ってから打ち直す）。
import { verdict } from "../src/rerun.js";
import { args, code, config, isNumber } from "./cli.js";

const { dry, rest: [id] } = args("node tools/flow-gate/bin/rerun.js <実行の id> [--dry-run]", (a) => a.length === 1 && isNumber(a[0]));
const repo = code();
const { repository, gather } = config.code;
const at = `/repos/${repository}/actions/runs/${id}`;
const run = await repo.rest("GET", at);
const { jobs } = await repo.rest("GET", `${at}/jobs?per_page=100`); // 既定は最後の試みのジョブ
// 注記を読むのは、段を走らせずに取り消されたジョブだけ（ジョブの id は、そのチェックの id でもある）。
const notes = {};
for (const j of jobs.filter((j) => j.conclusion === "cancelled" && !j.steps.length))
  notes[j.id] = (await repo.rest("GET", `/repos/${repository}/check-runs/${j.id}/annotations`)).map((a) => a.message);
const { kind, reason } = verdict(run, jobs, notes, gather);
if (kind === "流す" && !dry) await repo.rest("POST", `${at}/rerun-failed-jobs`);
console.log(`${dry && kind === "流す" ? "（試し）" : ""}${kind}: ${reason}`);
process.exit({ 流す: 0, 落ちた: 1, 使い切った: 3, 終わっていない: 4 }[kind]);

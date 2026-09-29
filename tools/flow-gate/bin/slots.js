// 担当のスロット（.claude/worktrees/ の coordinator.worktrees）の空きを出す。表は持たず、毎回作業ツリーの枝から組み立てる:
// 担当は始めるときに自分の枝（作る担当は code.branchPrefix + 番号、確かめる担当は coordinator.verifyPrefix + 番号）を取り、
// 終わるときに手放す（git checkout --detach）。枝を持っている作業ツリーは使用中で、その番号のキューの項目は動いている最中。
// 経過時間は、枝を取った時刻から。
// 使い方: node tools/flow-gate/bin/slots.js [--json] [作業ツリーの名前...]（名前を省くと coordinator.worktrees）
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import config from "../flow.config.json" with { type: "json" };

if (process.argv.slice(2).some((a) => a.startsWith("--") && a !== "--json")) {
  console.error("使い方: node tools/flow-gate/bin/slots.js [--json] [作業ツリーの名前...]");
  process.exit(2);
}
const named = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const SLOTS = named.length ? named : config.coordinator.worktrees;
const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8" }).trim();
const root = join(common, "..", ".claude", "worktrees");
const git = (dir, ...args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" }).trim();
const KINDS = [["作る", config.code.branchPrefix], ["確かめる", config.coordinator.verifyPrefix]];

const rows = [];
for (const slot of SLOTS) {
  const dir = join(root, slot);
  if (!existsSync(dir)) {
    rows.push({ slot, state: "無い" });
    continue;
  }
  const branch = git(dir, "branch", "--show-current");
  const dirty = git(dir, "status", "--porcelain") !== "";
  if (!branch) {
    rows.push({ slot, state: dirty ? "未コミットの変更あり" : "空き" });
    continue;
  }
  const [kind, prefix] = KINDS.find(([, p]) => branch.startsWith(p) && /^\d+$/.test(branch.slice(p.length))) ?? [null, null];
  const taken = Number(git(dir, "log", "-g", "-1", "--format=%ct", `refs/heads/${branch}`)) * 1000;
  rows.push({
    slot,
    state: "使用中",
    kind: kind ?? "不明な枝",
    number: kind ? Number(branch.slice(prefix.length)) : null,
    branch,
    minutes: Math.round((Date.now() - taken) / 60000),
  });
}

if (process.argv.includes("--json")) console.log(JSON.stringify(rows, null, 2));
else
  for (const r of rows)
    console.log(r.state === "使用中" ? `${r.slot} 使用中 ${r.kind}${r.number ? ` #${r.number}` : ` ${r.branch}`} ${r.minutes}分` : `${r.slot} ${r.state}`);

// 担当の作業ツリー（.claude/worktrees/ の coordinator.worktrees）を、どの issue が使っているかの表を出す。表は持たず、毎回事実から組み立てる:
// 使っている issue は作業ツリーのブランチ（code.branchPrefix + 番号）、経過時間は Project の Status の欄が最後に変わった時刻、規模は Project の規模の欄。
// 使い方: node tools/flow-gate/bin/slots.js [--json] [作業ツリーの名前...]（名前を省くと coordinator.worktrees）
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import config from "../flow.config.json" with { type: "json" };
import { GitHub, readTask } from "../src/github.js";
import { botToken } from "./token.js";

if (process.argv.slice(2).some((a) => a.startsWith("--") && a !== "--json")) {
  console.error("使い方: node tools/flow-gate/bin/slots.js [--json] [作業ツリーの名前...]");
  process.exit(2);
}
const named = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const SLOTS = named.length ? named : config.coordinator.worktrees;
const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8" }).trim();
const root = join(common, "..", ".claude", "worktrees");
const gh = new GitHub(botToken());
const git = (dir, ...args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" }).trim();
const prefix = config.code.branchPrefix;

const rows = [];
for (const slot of SLOTS) {
  const dir = join(root, slot);
  if (!existsSync(dir)) {
    rows.push({ slot, state: "無い" });
    continue;
  }
  const branch = git(dir, "branch", "--show-current");
  const dirty = git(dir, "status", "--porcelain") !== "";
  const number = branch.startsWith(prefix) && /^\d+$/.test(branch.slice(prefix.length)) ? branch.slice(prefix.length) : null;
  if (!number) {
    rows.push({ slot, state: dirty ? "未コミットの変更あり" : "空き" });
    continue;
  }
  const { issue } = await readTask(gh, config, { number: Number(number) });
  const d = await gh.gql(`query Since($id: ID!, $f: String!) { node(id: $id) { ... on ProjectV2Item {
    fieldValueByName(name: $f) { ... on ProjectV2ItemFieldSingleSelectValue { updatedAt } } } } }`, { id: issue.item, f: config.project.statusField });
  const since = d.node.fieldValueByName?.updatedAt;
  const busy = issue.state === "OPEN" && config.coordinator.busy.includes(issue.status);
  rows.push({
    slot,
    state: busy ? "使用中" : dirty ? "未コミットの変更あり" : "空き（前の作業の枝のまま）",
    number: Number(number),
    status: issue.status,
    minutes: since ? Math.round((Date.now() - Date.parse(since)) / 60000) : null,
    size: issue.fields[config.project.sizeField] ?? "",
    title: issue.title,
  });
}

if (process.argv.includes("--json")) console.log(JSON.stringify(rows, null, 2));
else
  for (const r of rows)
    console.log(r.number ? `${r.slot} ${r.state} #${r.number} ${r.status} ${r.minutes ?? "?"}分 ${r.size} ${r.title}` : `${r.slot} ${r.state}`);

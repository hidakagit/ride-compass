// 担当の作業ツリー（.claude/worktrees/w1〜w4）を、どの issue が使っているかの表を出す。表は持たず、毎回事実から組み立てる:
// 使っている issue は作業ツリーのブランチ（orch/tasks-<番号>）、経過時間は Project の Status の欄が最後に変わった時刻、規模はラベル。
// 使い方: node tools/flow-gate/bin/slots.js [--json] [作業ツリーの名前...]（名前を省くと w1〜w4）
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import config from "../flow.config.json" with { type: "json" };
import { GitHub, readTask } from "../src/github.js";
import { botToken } from "./token.js";

const named = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const SLOTS = named.length ? named : ["w1", "w2", "w3", "w4"];
const common = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8" }).trim();
const root = join(common, "..", ".claude", "worktrees");
const gh = new GitHub(botToken());
const git = (dir, ...args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" }).trim();

const rows = [];
for (const slot of SLOTS) {
  const dir = join(root, slot);
  if (!existsSync(dir)) {
    rows.push({ slot, state: "無い" });
    continue;
  }
  const branch = git(dir, "branch", "--show-current");
  const dirty = git(dir, "status", "--porcelain") !== "";
  const number = /^orch\/tasks-(\d+)$/.exec(branch)?.[1];
  if (!number) {
    rows.push({ slot, state: dirty ? "未コミットの変更あり" : "空き" });
    continue;
  }
  const { issue } = await readTask(gh, config, { number: Number(number) });
  const d = await gh.gql(`query Since($id: ID!, $f: String!) { node(id: $id) { ... on ProjectV2Item {
    fieldValueByName(name: $f) { ... on ProjectV2ItemFieldSingleSelectValue { updatedAt } } } } }`, { id: issue.item, f: config.project.statusField });
  const since = d.node.fieldValueByName?.updatedAt;
  const busy = issue.state === "OPEN" && ["進行中", "検証中"].includes(issue.status);
  rows.push({
    slot,
    state: busy ? "使用中" : dirty ? "未コミットの変更あり" : "空き（前の作業の枝のまま）",
    number: Number(number),
    status: issue.status,
    minutes: since ? Math.round((Date.now() - Date.parse(since)) / 60000) : null,
    size: issue.labels.nodes.map((l) => l.name).find((n) => n.startsWith("規模")) ?? "",
    title: issue.title,
  });
}

if (process.argv.includes("--json")) console.log(JSON.stringify(rows, null, 2));
else
  for (const r of rows)
    console.log(r.number ? `${r.slot} ${r.state} #${r.number} ${r.status} ${r.minutes ?? "?"}分 ${r.size} ${r.title}` : `${r.slot} ${r.state}`);

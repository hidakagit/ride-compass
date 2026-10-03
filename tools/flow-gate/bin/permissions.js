// 担当へ渡す設定を出す: 許可（src/permissions.js: permissionsOf。作業ツリーの docs/conventions/flow.md から組み立てる）と、自動モードの
// 判定役に教える環境と日常の作業（tools/flow-gate/automode.json の autoMode。判定役はリポジトリの .claude/settings.json の autoMode を読まない）。
// --added <版> は、その版の flow.md から組み立てた許可に無く、今の flow.md で増える許可の行だけを1行ずつ出す。
// 使い方: node tools/flow-gate/bin/permissions.js [--added <版>]
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { permissionsOf } from "../src/permissions.js";

const args = process.argv.slice(2);
if (!(args.length === 0 || (args.length === 2 && args[0] === "--added"))) {
  console.error("使い方: node tools/flow-gate/bin/permissions.js [--added <版>]");
  process.exit(2);
}
const path = "docs/conventions/flow.md";
const root = new URL("../../../", import.meta.url);
const now = permissionsOf(readFileSync(new URL(path, root), "utf8"));
const autoMode = JSON.parse(readFileSync(new URL("../automode.json", import.meta.url), "utf8"));

if (args.length === 0) console.log(JSON.stringify({ permissions: now, autoMode }));
else {
  const before = new Set(permissionsOf(execFileSync("git", ["show", `${args[1]}:${path}`], { cwd: root, encoding: "utf8" })).allow);
  for (const row of now.allow.filter((row) => !before.has(row))) console.log(row);
}

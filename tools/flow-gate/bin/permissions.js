// 担当へ渡す設定を出す: 許可（src/permissions.js: permissionsOf。作業ツリーの docs/conventions/flow.md から組み立てる）と、自動モードの
// 判定役に教える環境と日常の作業（tools/flow-gate/automode.json の autoMode。判定役はリポジトリの .claude/settings.json の autoMode を読まない）。
// --added <版> は、その版の道具が出す設定から今の設定で担当の権限が広がる所（増えた許可・消えた拒否・変わった autoMode の文）を1行ずつ出す。
// その版の設定はその版の道具で組み立てる（今の規則で前の flow.md を組み立てると、規則の側で消した拒否が前後のどちらにも効かず、差に出ない）。
// 使い方: node tools/flow-gate/bin/permissions.js [--added <版>]
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { permissionsOf } from "../src/permissions.js";

const args = process.argv.slice(2);
if (!(args.length === 0 || (args.length === 2 && args[0] === "--added"))) {
  console.error("使い方: node tools/flow-gate/bin/permissions.js [--added <版>]");
  process.exit(2);
}
const path = "docs/conventions/flow.md";
const root = fileURLToPath(new URL("../../../", import.meta.url));
const now = {
  permissions: permissionsOf(readFileSync(join(root, path), "utf8")),
  autoMode: JSON.parse(readFileSync(new URL("../automode.json", import.meta.url), "utf8")),
};

if (args.length === 0) console.log(JSON.stringify(now));
else for (const line of widened(settingsAt(args[1]), now)) console.log(line);

// その版の道具と flow.md を作業ツリーの外へ取り出し、その版の道具に設定を出させる。
function settingsAt(rev) {
  const git = (...rest) => execFileSync("git", rest, { cwd: root });
  const dir = mkdtempSync(join(tmpdir(), "permissions-"));
  try {
    for (const file of git("ls-tree", "-r", "--name-only", "-z", rev, "--", "tools/flow-gate", path).toString().split("\0")) {
      if (!file) continue;
      mkdirSync(dirname(join(dir, file)), { recursive: true });
      writeFileSync(join(dir, file), git("show", `${rev}:${file}`));
    }
    return JSON.parse(execFileSync(process.execPath, [join(dir, "tools/flow-gate/bin/permissions.js")], { encoding: "utf8" }));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

function widened(before, after) {
  const minus = (a = [], b = []) => a.filter((row) => !b.includes(row));
  const lines = [
    ...minus(after.permissions.allow, before.permissions.allow).map((row) => `許可に増えた: ${row}`),
    ...minus(before.permissions.deny, after.permissions.deny).map((row) => `拒否から消えた: ${row}`),
  ];
  for (const name of new Set([...Object.keys(before.autoMode), ...Object.keys(after.autoMode)])) {
    lines.push(...minus(after.autoMode[name], before.autoMode[name]).map((text) => `autoMode.${name} に増えた: ${text}`));
    lines.push(...minus(before.autoMode[name], after.autoMode[name]).map((text) => `autoMode.${name} から消えた: ${text}`));
  }
  return lines;
}

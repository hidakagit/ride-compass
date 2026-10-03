// 担当へ渡す許可（src/permissions.js: permissionsOf）を、作業ツリーの docs/conventions/flow.md から組み立てて設定の形で出す。
// --added <基の版> [<比べる版>] は、基の版の flow.md から組み立てた許可に無く、比べる側の flow.md で増える許可の行だけを1行ずつ出す。
// 比べる側は、比べる版を渡せばそれを基の版と合わせた版（git merge-tree）、渡さなければ作業ツリー。両側とも基の版の permissionsOf で
// 組み立てるので、許可を判じるのは基の版の規則で、比べる側の道具の版によらない。
// 使い方: node tools/flow-gate/bin/permissions.js [--added <基の版> [<比べる版>]]
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { permissionsOf } from "../src/permissions.js";

const args = process.argv.slice(2);
if (!(args.length === 0 || ((args.length === 2 || args.length === 3) && args[0] === "--added"))) {
  console.error("使い方: node tools/flow-gate/bin/permissions.js [--added <基の版> [<比べる版>]]");
  process.exit(2);
}
const path = "docs/conventions/flow.md";
const root = new URL("../../../", import.meta.url);
const git = (...rest) => execFileSync("git", rest, { cwd: root, encoding: "utf8" });

if (args.length === 0) console.log(JSON.stringify({ permissions: permissionsOf(readFileSync(new URL(path, root), "utf8")) }));
else {
  const [, base, head] = args;
  const rules = await import(
    `data:text/javascript,${encodeURIComponent(git("show", `${base}:tools/flow-gate/src/permissions.js`))}`
  );
  let flow;
  if (head === undefined) flow = readFileSync(new URL(path, root), "utf8");
  else {
    let tree;
    try {
      tree = git("merge-tree", "--write-tree", base, head).split("\n")[0];
    } catch {
      console.error(`${head} を ${base} と合わせると競合する（git merge-tree --write-tree ${base} ${head}）`);
      process.exit(1);
    }
    flow = git("show", `${tree}:${path}`);
  }
  const before = new Set(rules.permissionsOf(git("show", `${base}:${path}`)).allow);
  for (const row of rules.permissionsOf(flow).allow.filter((row) => !before.has(row))) console.log(row);
}

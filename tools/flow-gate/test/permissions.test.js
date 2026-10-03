// 担当へ渡す許可が、flow.md に書いた操作から組み立てられ、決して許さない操作を許可にしないこと。権限の広がりが --added に出ること。
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { DENY, permissionsOf } from "../src/permissions.js";

const flow = readFileSync(new URL("../../../docs/conventions/flow.md", import.meta.url), "utf8");

test("操作の置き場所は * になり、WebFetch は宛先の行になる", () => {
  const { allow, deny } = permissionsOf(
    "`git push origin orch/tasks-<番号>` と `gh run watch <id> -R o/r --exit-status`、`WebFetch https://raw.githubusercontent.com/<所有者>/<パス>`。`npm test` は拾わない",
  );
  assert.deepEqual(allow, [
    "Bash(gh run watch * -R o/r --exit-status)",
    "Bash(git push origin orch/tasks-*)",
    "WebFetch(domain:raw.githubusercontent.com)",
  ]);
  assert.deepEqual(deny, DENY);
});

test("決して許さない操作は、flow.md に書いてあっても許可にならない", () => {
  const forbidden = [
    "git push origin master",
    "git push origin HEAD:master",
    "git push --force origin orch/tasks-<番号>",
    "git push origin orch/tasks-<番号> -f",
    "gh api repos/o/r/issues/<番号> -X PATCH",
    "gh api repos/o/r/actions/variables --method POST",
    "gh workflow run claude-dispatch.yml -R o/r",
    "gh secret set X",
    "gh pr merge <番号> -R o/r --rebase --admin",
  ];
  const kept = "git push --force-with-lease origin orch/tasks-<番号>";
  const { allow } = permissionsOf([...forbidden, kept].map((c) => `\`${c}\``).join(" "));
  assert.deepEqual(allow, ["Bash(git push --force-with-lease origin orch/tasks-*)"]);
});

test("本物の flow.md から組み立てた許可は、どれも頭の語が * でなく、push・マージ・CI の待ちを持つ", () => {
  const { allow } = permissionsOf(flow);
  for (const row of allow.filter((r) => r.startsWith("Bash("))) {
    assert.ok(!/^Bash\(\S+ \*/.test(row), `${row} は * が操作の頭の語より前にある`);
  }
  for (const head of ["Bash(git push origin orch/tasks-", "Bash(gh pr merge ", "Bash(gh run watch "]) {
    assert.ok(allow.some((r) => r.startsWith(head)), `${head} で始まる許可が無い`);
  }
});

test("判定役に渡す autoMode の一覧は、どれも既定の規則（$defaults）を残す（書かないと、その一覧の既定の守りを全部捨てる）", async () => {
  const autoMode = JSON.parse(readFileSync(new URL("../automode.json", import.meta.url), "utf8"));
  assert.ok(Object.keys(autoMode).length > 0);
  for (const [name, list] of Object.entries(autoMode)) assert.ok(Array.isArray(list) && list.includes("$defaults"), name);
});

// 前の版は前の版の道具で組み立てるので、規則の側（DENY・automode.json）だけを変えた差分も広がりとして出る。
test("--added は、増えた許可・消えた拒否・変わった autoMode の文を出し、変更が無ければ何も出さない", () => {
  const dir = mkdtempSync(join(tmpdir(), "permissions-"));
  const sh = (...rest) => execFileSync("git", rest, { cwd: dir, encoding: "utf8", stdio: "pipe" });
  const write = (path, text) => {
    mkdirSync(dirname(join(dir, path)), { recursive: true });
    writeFileSync(join(dir, path), text);
  };
  const files = {
    "docs/conventions/flow.md": "`git status`\n",
    ...Object.fromEntries(
      ["bin/permissions.js", "src/permissions.js", "automode.json", "package.json"].map((path) => [
        `tools/flow-gate/${path}`,
        readFileSync(new URL(`../${path}`, import.meta.url), "utf8"),
      ]),
    ),
  };
  const added = (changes) => {
    for (const [path, text] of Object.entries(files)) write(path, changes[path]?.(text) ?? text);
    return execFileSync(process.execPath, ["tools/flow-gate/bin/permissions.js", "--added", "master"], { cwd: dir, encoding: "utf8" });
  };
  try {
    sh("init", "-q", "-b", "master");
    for (const [path, text] of Object.entries(files)) write(path, text);
    sh("add", "-A");
    sh("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "前の版");
    assert.equal(added({}), "");
    assert.equal(
      added({
        "tools/flow-gate/automode.json": (text) =>
          JSON.stringify({ ...JSON.parse(text), allow: [...JSON.parse(text).allow, "Anything goes."] }),
      }),
      "autoMode.allow に増えた: Anything goes.\n",
    );
    assert.equal(
      added({
        "tools/flow-gate/src/permissions.js": (text) => text.replace('  "Bash(git clean *)",\n', ""),
        "docs/conventions/flow.md": (text) => `${text}\`git clean -fd\`\n`,
      }),
      "許可に増えた: Bash(git clean -fd)\n拒否から消えた: Bash(git clean *)\n",
    );
    assert.equal(
      added({ "docs/conventions/flow.md": (text) => `${text}\`gh issue list <番号>\`\n` }),
      "許可に増えた: Bash(gh issue list *)\n",
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// 担当へ渡す許可が、flow.md に書いた操作から組み立てられ、決して許さない操作を許可にしないこと。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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

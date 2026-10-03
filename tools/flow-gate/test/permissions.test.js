// 担当は無人で動き、許可の一覧に合わない操作は自動モードの判定役が1回ずつ可否を決める。flow.md に書いた形のまま打てば
// 一覧の行に合うことを、本物の flow.md と .claude/settings.json で確かめる。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const root = new URL("../../../", import.meta.url);
const flow = readFileSync(new URL("docs/conventions/flow.md", root), "utf8");
const settings = JSON.parse(readFileSync(new URL(".claude/settings.json", root), "utf8"));

// 行の頭（何の操作か）は、git なら2語・gh なら3語（例: `git push`・`gh pr merge`）。
const head = (command) => command.split(/\s+/).slice(0, command.startsWith("gh ") ? 3 : 2).join(" ");
const rows = settings.permissions.allow.map((row) => {
  const [, shell, pattern] = row.match(/^(\w+)\((.*)\)$/);
  const glob = new RegExp(`^${pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*")}$`);
  return { row, shell, head: head(pattern), matches: (command) => glob.test(command) };
});
// flow.md の `…` のうち、許可の一覧がその種類の操作を持つもの。<番号> 等の置き場所には値を入れて照らす。
const commands = [...flow.matchAll(/`((?:git|gh) [^`]+)`/g)]
  .map((m) => m[1].replace(/<[^>]+>/g, "1"))
  .filter((command) => rows.some((r) => r.head === head(command)));

test("flow.md に書いた操作は、Bash と PowerShell の両方で許可の行に合う", () => {
  assert.ok(commands.length > 0);
  for (const command of commands) {
    for (const shell of ["Bash", "PowerShell"]) {
      assert.ok(
        rows.some((r) => r.shell === shell && r.matches(command)),
        `flow.md の \`${command}\` に合う ${shell} の許可の行が無い`,
      );
    }
  }
});

test("許可の行は、どれも flow.md に書いた操作に使われている", () => {
  for (const r of rows) {
    assert.ok(commands.some((command) => r.matches(command)), `${r.row} を使う操作が flow.md に無い`);
  }
});

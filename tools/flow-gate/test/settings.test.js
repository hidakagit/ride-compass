// 担当へ渡す設定（tools/flow-gate/settings.json）の不変条件。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

test("判定役に渡す autoMode の一覧は、どれも既定の規則（$defaults）を残す（書かないと、その一覧の既定の守りを全部捨てる）", () => {
  const { autoMode } = JSON.parse(readFileSync(new URL("../settings.json", import.meta.url), "utf8"));
  assert.ok(Object.keys(autoMode).length > 0);
  for (const [name, list] of Object.entries(autoMode)) assert.ok(Array.isArray(list) && list.includes("$defaults"), name);
});

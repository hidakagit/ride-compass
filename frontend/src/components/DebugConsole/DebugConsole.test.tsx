import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { DEBUG_CONSOLE_MAX_HEIGHT_PX } from "./DebugConsole";

// DebugConsole.module.cssのmax-heightは、page.tsxが「現在地に移動」ボタンをデバッグ
// モード表示中にDebugConsoleの上へ逃がす計算（DEBUG_CONSOLE_MAX_HEIGHT_PXを参照）の
// 前提になっている。CSS側の値だけを変更するとボタンとログが再び重なってしまうため、
// 一致していることを自動検証する。
describe("DEBUG_CONSOLE_MAX_HEIGHT_PX とDebugConsole.module.cssの整合性", () => {
  it("DebugConsole.module.cssのmax-heightと同じ値を使っている", () => {
    const cssPath = path.resolve(process.cwd(), "src/components/DebugConsole/DebugConsole.module.css");
    const css = readFileSync(cssPath, "utf-8");
    const match = css.match(/max-height:\s*(\d+)px/);

    expect(match).not.toBeNull();
    expect(Number(match![1])).toBe(DEBUG_CONSOLE_MAX_HEIGHT_PX);
  });
});

// @vitest-environment node
/**
 * スマホ幅の印をCSSが立てる取り決め。
 *
 * スマホ幅かどうかの判定はCSSのメディアクエリだけが持ち、画面のコード（`hooks/useIsMobile.ts: useIsMobile`）は
 * 根の要素の`--is-mobile`を読むだけである。CSSがメディアクエリの中で印を立てなくなると、画面のコードは
 * どの幅でもスマホ幅でないと答え続け、スマホでもデスクトップの配置で描く。
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("CSSとの取り決め", () => {
  it("globals.cssは幅のメディアクエリの中で`--is-mobile`を立てる", () => {
    const css = readFileSync(path.resolve(process.cwd(), "src/app/globals.css"), "utf-8");
    const mediaBlock = css.match(/@media \(max-width:[\s\S]*?\)\s*\{[\s\S]*?\n\}/);

    expect(mediaBlock).not.toBeNull();
    expect(mediaBlock![0]).toContain("--is-mobile: 1");
  });
});

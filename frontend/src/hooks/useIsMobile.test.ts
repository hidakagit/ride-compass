import { renderHook } from "@testing-library/react";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useIsMobile } from "./useIsMobile";

/** CSSが立てる旗を差し替える。**幅の数値はここに書かない**——数値はCSSだけが持つ。 */
function mockIsMobileFlag(value: "0" | "1") {
  vi.spyOn(window, "getComputedStyle").mockReturnValue({
    getPropertyValue: (name: string) => (name === "--is-mobile" ? value : ""),
  } as unknown as CSSStyleDeclaration);
}

describe("useIsMobile", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("CSSの旗が立っていればモバイル判定になる", () => {
    mockIsMobileFlag("1");

    expect(renderHook(() => useIsMobile()).result.current).toBe(true);
  });

  it("立っていなければデスクトップ判定になる", () => {
    mockIsMobileFlag("0");

    expect(renderHook(() => useIsMobile()).result.current).toBe(false);
  });
});

// 旗が無ければフックは常にfalseを返し、モバイルのドロワーが開かないまま黙って動く。
// **値は照合しない**（数値はCSSにしか無い）。旗が幅の分岐の中で立っていることだけを見る。
describe("CSSとの取り決め", () => {
  it("globals.cssは幅のメディアクエリの中で`--is-mobile`を立てる", () => {
    const css = readFileSync(path.resolve(process.cwd(), "src/app/globals.css"), "utf-8");
    const mediaBlock = css.match(/@media \(max-width:[\s\S]*?\)\s*\{[\s\S]*?\n\}/);

    expect(mediaBlock).not.toBeNull();
    expect(mediaBlock![0]).toContain("--is-mobile: 1");
    expect(css).toContain("--is-mobile: 0");
  });
});

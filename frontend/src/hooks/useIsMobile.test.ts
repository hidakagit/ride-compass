import { renderHook } from "@testing-library/react";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MOBILE_BREAKPOINT_PX, useIsMobile } from "./useIsMobile";

function mockMatchMedia(matches: boolean) {
  const target = new EventTarget();
  const mql = {
    matches,
    media: "",
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
  } as unknown as MediaQueryList;
  window.matchMedia = vi.fn().mockReturnValue(mql);
  return mql;
}

describe("useIsMobile", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("matchMediaの初期matchesがtrueならモバイル判定になる", () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it("matchMediaの初期matchesがfalseならデスクトップ判定になる", () => {
    mockMatchMedia(false);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });
});

// globals.cssの`@media (max-width: ...)`はJSのMOBILE_BREAKPOINT_PXと手動で値を
// 一致させる必要がある（CSSファイルからJSの定数を直接参照する仕組みがないため）。
// 片方だけ変更されて値がズレると、CSS上はオーバーレイ表示に切り替わっているのに
// JS側はデスクトップ判定のまま、というモバイルドロワーの不具合につながる。
describe("MOBILE_BREAKPOINT_PX とglobals.cssの整合性", () => {
  it("globals.cssの@media (max-width: ...)と同じ値を使っている", () => {
    const cssPath = path.resolve(process.cwd(), "src/app/globals.css");
    const css = readFileSync(cssPath, "utf-8");
    const match = css.match(/@media \(max-width:\s*(\d+)px\)/);

    expect(match).not.toBeNull();
    expect(Number(match![1])).toBe(MOBILE_BREAKPOINT_PX);
  });
});

/**
 * スマホ幅かどうか（`hooks/useIsMobile.ts: useIsMobile`）——CSS が根の要素に置く印（`--is-mobile`）を読み、
 * 窓の大きさが変わるたびに読み直す。
 *
 * ここで見ないもの:
 * - どの幅で印が立つか → `app/globals.css` のメディアクエリ（テスト環境はメディアクエリで印を切り替えない）
 * - スマホ幅でどう描き分けるか → 呼び出し側の部品
 *
 * 差し替えたものは無い。印はテスト環境の根の要素へ直接置く。
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useIsMobile } from "./useIsMobile";

function setMobileFlag(value: string) {
  document.documentElement.style.setProperty("--is-mobile", value);
}

function resizeWindow() {
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });
}

afterEach(() => {
  document.documentElement.style.removeProperty("--is-mobile");
});

describe("useIsMobile", () => {
  it("印が 1 なら、描いた時点でスマホ幅と答える（前後の空白は見ない）", () => {
    setMobileFlag(" 1 ");

    const { result } = renderHook(() => useIsMobile());

    expect(result.current).toBe(true);
  });

  it("窓の大きさが変わるたびに印を読み直す", () => {
    setMobileFlag("0");
    const { result } = renderHook(() => useIsMobile());

    setMobileFlag("1");
    resizeWindow();
    expect(result.current).toBe(true);

    setMobileFlag("0");
    resizeWindow();
    expect(result.current).toBe(false);
  });
});

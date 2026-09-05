import { renderHook } from "@testing-library/react";
import { useRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useElementHeightCssVar } from "./useElementHeightCssVar";

// jsdomはResizeObserverを実装しない（AxisStudio.test.tsxと
// 同じ既知の欠落への対処、同じ最小モックを使う）。
class ResizeObserverMock {
  callback: ResizeObserverCallback;
  observed: Element[] = [];
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }
  observe = vi.fn((el: Element) => {
    this.observed.push(el);
  });
  unobserve = vi.fn();
  disconnect = vi.fn();
}

describe("useElementHeightCssVar", () => {
  beforeEach(() => {
    window.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
  });

  function renderWithRefs() {
    return renderHook(() => {
      const measureRef = useRef<HTMLDivElement>(null);
      const targetRef = useRef<HTMLDivElement>(null);
      if (!measureRef.current) {
        measureRef.current = document.createElement("div");
      }
      if (!targetRef.current) {
        targetRef.current = document.createElement("div");
      }
      useElementHeightCssVar(measureRef, targetRef, "--test-height");
      return { measureRef, targetRef };
    });
  }

  it("マウント時にtargetRefへCSS変数を初期値でセットする", () => {
    const { result } = renderWithRefs();

    expect(result.current.targetRef.current?.style.getPropertyValue("--test-height")).toBe("0px");
  });

  it("アンマウント時にtargetRefからCSS変数を削除する", () => {
    const { result, unmount } = renderWithRefs();
    expect(result.current.targetRef.current?.style.getPropertyValue("--test-height")).toBe("0px");

    unmount();

    expect(result.current.targetRef.current?.style.getPropertyValue("--test-height")).toBe("");
  });

  it("measureRefまたはtargetRefが無い場合は何もせず例外を投げない", () => {
    expect(() =>
      renderHook(() => {
        const measureRef = useRef<HTMLDivElement>(null);
        const targetRef = useRef<HTMLDivElement>(null);
        useElementHeightCssVar(measureRef, targetRef, "--test-height");
      }),
    ).not.toThrow();
  });
});

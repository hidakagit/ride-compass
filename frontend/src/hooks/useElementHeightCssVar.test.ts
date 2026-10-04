/**
 * 要素の高さを祖先の CSS 変数へ書き続けるフック（`hooks/useElementHeightCssVar.ts: useElementHeightCssVar`）——
 * 書き始めた時点の高さを書き、大きさが変わるたびに書き直し、外れたら変数を消す。
 *
 * ここで見ないもの:
 * - 変数を読んで位置をずらす CSS → 呼び出し側の部品（実寸はテスト環境に無い）
 *
 * 差し替えたもの: テスト環境に無いレイアウトの実寸——要素の高さ（`getBoundingClientRect`）と、大きさの変化を
 * 知らせる `ResizeObserver`。代役は観察中の要素へだけ知らせ、`disconnect` のあとは知らせない（本物と同じ約束）。
 */
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useElementHeightCssVar } from "./useElementHeightCssVar";

const VAR = "--measured-height";

/** 観察中の要素と、その知らせ先。 */
const observing = new Map<Element, Set<ResizeObserverCallback>>();

class FakeResizeObserver {
  private readonly targets = new Set<Element>();
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe(target: Element) {
    this.targets.add(target);
    if (!observing.has(target)) observing.set(target, new Set());
    observing.get(target)!.add(this.callback);
  }
  unobserve(target: Element) {
    this.targets.delete(target);
    observing.get(target)?.delete(this.callback);
  }
  disconnect() {
    for (const target of [...this.targets]) this.unobserve(target);
  }
}

/** 要素の大きさが変わったことを、観察している側へ知らせる。 */
function resize(element: Element, entries: Partial<ResizeObserverEntry>[]) {
  for (const callback of observing.get(element) ?? []) {
    callback(entries as ResizeObserverEntry[], {} as ResizeObserver);
  }
}

function elementOfHeight(height: number): HTMLElement {
  const element = document.createElement("div");
  element.getBoundingClientRect = () => ({ height }) as DOMRect;
  return element;
}

function mount(measure: HTMLElement, target: HTMLElement) {
  return renderHook(() => useElementHeightCssVar({ current: measure }, { current: target }, VAR));
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
  observing.clear();
});

describe("useElementHeightCssVar", () => {
  it("書き始めた時点の高さを、祖先の変数へ px で書く", () => {
    const target = document.createElement("div");

    mount(elementOfHeight(42), target);

    expect(target.style.getPropertyValue(VAR)).toBe("42px");
  });

  it("大きさが変わるたびに、知らされた高さで書き直す", () => {
    const measure = elementOfHeight(42);
    const target = document.createElement("div");
    mount(measure, target);

    resize(measure, [{ contentRect: { height: 64 } as DOMRectReadOnly }]);

    expect(target.style.getPropertyValue(VAR)).toBe("64px");
  });

  it("外れると変数を消し、そのあと大きさが変わっても書かない", () => {
    const measure = elementOfHeight(42);
    const target = document.createElement("div");
    const { unmount } = mount(measure, target);

    unmount();
    resize(measure, [{ contentRect: { height: 64 } as DOMRectReadOnly }]);

    expect(target.style.getPropertyValue(VAR)).toBe("");
  });
});

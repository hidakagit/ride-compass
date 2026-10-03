/**
 * 値の変化を遅らせて返すフック（`hooks/useDebouncedValue.ts: useDebouncedValue`）——初回の値はそのまま返し、
 * 変化は最後に変わってから待ち時間が経ったときに、最後の値だけを返す。
 *
 * ここで見ないもの:
 * - どの値をどれだけ遅らせるか（地図の取得の間引き等） → 呼び出し側のフックのテスト
 *
 * 差し替えたもの: 時計（`vi.useFakeTimers`）。
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebouncedValue } from "./useDebouncedValue";

const DELAY_MS = 300;

function mount(value: string, delayMs = DELAY_MS) {
  return renderHook(({ value, delayMs }) => useDebouncedValue(value, delayMs), { initialProps: { value, delayMs } });
}

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useDebouncedValue", () => {
  it("初回の値は待たずにそのまま返す", () => {
    const { result } = mount("a");

    expect(result.current).toBe("a");
  });

  it("変わった値は、待ち時間が経つまで前の値のまま、経ったら新しい値になる", () => {
    const { result, rerender } = mount("a");

    rerender({ value: "b", delayMs: DELAY_MS });
    advance(DELAY_MS - 1);
    expect(result.current).toBe("a");

    advance(1);
    expect(result.current).toBe("b");
  });

  it("待っている間に続けて変わると、最後に変わってから数え直し、途中の値を返さない", () => {
    const { result, rerender } = mount("a");

    rerender({ value: "b", delayMs: DELAY_MS });
    advance(DELAY_MS - 1);
    rerender({ value: "c", delayMs: DELAY_MS });
    advance(DELAY_MS - 1);
    expect(result.current).toBe("a");

    advance(1);
    expect(result.current).toBe("c");
  });

  it("待っている間に待ち時間が変わると、新しい待ち時間で数え直す", () => {
    const { result, rerender } = mount("a");

    rerender({ value: "b", delayMs: DELAY_MS });
    advance(DELAY_MS - 1);
    rerender({ value: "b", delayMs: DELAY_MS * 2 });
    advance(DELAY_MS * 2 - 1);
    expect(result.current).toBe("a");

    advance(1);
    expect(result.current).toBe("b");
  });
});

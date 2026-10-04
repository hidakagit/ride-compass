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

function mount(value: string) {
  return renderHook(({ value }) => useDebouncedValue(value, DELAY_MS), { initialProps: { value } });
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
  it("初回の値は待たずに返し、変わった値は、待ち時間が経つまで前の値のまま、経ったら新しい値になる", () => {
    const { result, rerender } = mount("a");
    expect(result.current).toBe("a");

    rerender({ value: "b" });
    advance(DELAY_MS - 1);
    expect(result.current).toBe("a");

    advance(1);
    expect(result.current).toBe("b");
  });

  it("待っている間に続けて変わると、最後に変わってから数え直し、途中の値を返さない", () => {
    const { result, rerender } = mount("a");

    rerender({ value: "b" });
    advance(DELAY_MS - 1);
    rerender({ value: "c" });
    advance(DELAY_MS - 1);
    expect(result.current).toBe("a");

    advance(1);
    expect(result.current).toBe("c");
  });
});

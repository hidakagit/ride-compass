import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDebouncedValue } from "./useDebouncedValue";

describe("useDebouncedValue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("初期値は即座に返す", () => {
    const { result } = renderHook(() => useDebouncedValue("a", 400));
    expect(result.current).toBe("a");
  });

  it("値の変更はdelayMs経過後に反映される", () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 400), {
      initialProps: { value: "a" },
    });

    rerender({ value: "b" });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(result.current).toBe("b");
  });

  it("delayMs内に連続で変更すると最後の値だけが反映される（連続タップの合流）", () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 400), {
      initialProps: { value: "a" },
    });

    rerender({ value: "b" });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    rerender({ value: "c" });
    act(() => {
      vi.advanceTimersByTime(399);
    });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe("c");
  });
});

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRecipeOverride } from "./useRecipeOverride";

describe("useRecipeOverride", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("初期値はoverrideEnabled=false・recipe/debouncedRecipeとも既定レシピ", () => {
    const { result } = renderHook(() => useRecipeOverride({ base: 1 }, 400, "test:initial"));

    expect(result.current.overrideEnabled).toBe(false);
    expect(result.current.recipe).toEqual({ base: 1 });
    expect(result.current.debouncedRecipe).toEqual({ base: 1 });
  });

  it("setOverrideEnabledで有効フラグが即座に切り替わる", () => {
    const { result } = renderHook(() => useRecipeOverride({ base: 1 }, 400, "test:enabled"));

    act(() => {
      result.current.setOverrideEnabled(true);
    });

    expect(result.current.overrideEnabled).toBe(true);
  });

  it("setRecipeでrecipeは即座に、debouncedRecipeはdebounceMs経過後に更新される", () => {
    const { result } = renderHook(() => useRecipeOverride({ base: 1 }, 400, "test:debounce"));

    act(() => {
      result.current.setRecipe({ base: 2 });
    });

    expect(result.current.recipe).toEqual({ base: 2 });
    expect(result.current.debouncedRecipe).toEqual({ base: 1 });

    act(() => {
      vi.advanceTimersByTime(400);
    });

    expect(result.current.debouncedRecipe).toEqual({ base: 2 });
  });

  it("storageKeyが同じであればlocalStorage経由で値が復元される", () => {
    const { result: first } = renderHook(() => useRecipeOverride({ base: 1 }, 400, "test:shared"));
    act(() => {
      first.current.setOverrideEnabled(true);
      first.current.setRecipe({ base: 9 });
    });

    const { result: second } = renderHook(() => useRecipeOverride({ base: 1 }, 400, "test:shared"));

    expect(second.current.overrideEnabled).toBe(true);
    expect(second.current.recipe).toEqual({ base: 9 });
  });
});

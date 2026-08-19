import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRecipeOverride } from "./useRecipeOverride";

describe("useRecipeOverride", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("初期値はoverrideEnabled=false・recipe/debouncedRecipeとも既定レシピ", () => {
    const { result } = renderHook(() => useRecipeOverride({ base: 1 }, 400));

    expect(result.current.overrideEnabled).toBe(false);
    expect(result.current.recipe).toEqual({ base: 1 });
    expect(result.current.debouncedRecipe).toEqual({ base: 1 });
  });

  it("setOverrideEnabledで有効フラグが即座に切り替わる", () => {
    const { result } = renderHook(() => useRecipeOverride({ base: 1 }, 400));

    act(() => {
      result.current.setOverrideEnabled(true);
    });

    expect(result.current.overrideEnabled).toBe(true);
  });

  it("setRecipeでrecipeは即座に、debouncedRecipeはdebounceMs経過後に更新される", () => {
    const { result } = renderHook(() => useRecipeOverride({ base: 1 }, 400));

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
});

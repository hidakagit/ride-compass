// `useDepartureTime.ts`——出発時刻。選ぶまでは「今」へ追従し、選んだ時刻は動かさない。
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDepartureTime } from "./useDepartureTime";

const STEP_MS = 5 * 60 * 1000;
// 5分境界ちょうどではない時刻から始め、丸めが効いていることも同時に見る。
const T0 = Date.UTC(2026, 8, 15, 10, 2, 30);
const stepped = (ms: number) => Math.floor(ms / STEP_MS) * STEP_MS;

describe("useDepartureTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
  });
  afterEach(() => vi.useRealTimers());

  it("選ぶまでは5分刻みの「今」へ追従して進む", () => {
    const { result } = renderHook(() => useDepartureTime());
    expect(result.current.at.getTime()).toBe(stepped(T0));
    expect(result.current.pinned).toBe(false);

    act(() => vi.advanceTimersByTime(11 * 60 * 1000));
    expect(result.current.at.getTime()).toBe(stepped(T0 + 11 * 60 * 1000));
  });

  it("利用者が選んだ時刻は、時間が経っても動かない", () => {
    const chosen = new Date(T0 + 30 * 60 * 1000);
    const { result } = renderHook(() => useDepartureTime());
    act(() => result.current.setAt(chosen));
    act(() => vi.advanceTimersByTime(11 * 60 * 1000));
    expect(result.current.at.getTime()).toBe(chosen.getTime());
    expect(result.current.pinned).toBe(true);
  });

  it("「今」へ戻すと、その時点の「今」から再び追従する", () => {
    const { result } = renderHook(() => useDepartureTime());
    act(() => result.current.setAt(new Date(T0 + 30 * 60 * 1000)));
    act(() => vi.advanceTimersByTime(11 * 60 * 1000));
    act(() => result.current.followNow());
    expect(result.current.at.getTime()).toBe(stepped(T0 + 11 * 60 * 1000));

    act(() => vi.advanceTimersByTime(11 * 60 * 1000));
    expect(result.current.at.getTime()).toBe(stepped(T0 + 22 * 60 * 1000));
  });
});

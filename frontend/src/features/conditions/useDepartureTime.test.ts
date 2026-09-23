import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDepartureTime } from "./useDepartureTime";

const at = (text: string) => new Date(`${text}+09:00`);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(at("2026-09-24T09:07:20"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useDepartureTime（出発時刻）", () => {
  it("選ぶまでは、5分刻みへ切り下げた「今」を出発時刻にする", () => {
    const { result } = renderHook(() => useDepartureTime());
    expect(result.current.at).toEqual(at("2026-09-24T09:05"));
    expect(result.current.pinned).toBe(false);
  });

  it("「今」は刻みを跨いだときだけ進み、同じ刻みの間は値そのものを変えない", () => {
    const { result } = renderHook(() => useDepartureTime());
    const before = result.current.now;
    act(() => vi.advanceTimersByTime(60_000));
    expect(result.current.now).toBe(before);
    act(() => vi.advanceTimersByTime(3 * 60_000));
    expect(result.current.at).toEqual(at("2026-09-24T09:10"));
  });

  it("選んだ時刻は、時間が経っても動かさない", () => {
    const { result } = renderHook(() => useDepartureTime());
    act(() => result.current.setAt(at("2026-09-24T15:30")));
    act(() => vi.advanceTimersByTime(30 * 60_000));
    expect(result.current.at).toEqual(at("2026-09-24T15:30"));
    expect(result.current.pinned).toBe(true);
    expect(result.current.now).toEqual(at("2026-09-24T09:35"));
  });

  it("「今」への追従へ戻すと、その時点の「今」になる", () => {
    const { result } = renderHook(() => useDepartureTime());
    act(() => result.current.setAt(at("2026-09-24T15:30")));
    vi.setSystemTime(at("2026-09-24T09:21:00"));
    act(() => result.current.followNow());
    expect(result.current.at).toEqual(at("2026-09-24T09:20"));
    expect(result.current.pinned).toBe(false);
  });
});

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { debugLog } = vi.hoisted(() => ({ debugLog: vi.fn() }));
vi.mock("@/lib/debugLog", () => ({ debugLog }));

import { usePolledFetch } from "./usePolledFetch";

const INTERVAL_MS = 60_000;
const OPTIONS = { intervalMs: INTERVAL_MS, label: "テスト対象" };

async function settle() {
  await act(async () => {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  debugLog.mockClear();
});
afterEach(() => {
  vi.useRealTimers();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("usePolledFetch（定期取得）", () => {
  it("有効な間だけ、すぐ1回取り、以後は間隔ごとに取り直す", async () => {
    const fetcher = vi.fn(async () => fetcher.mock.calls.length);
    const { result } = renderHook(() => usePolledFetch(fetcher, 0, { ...OPTIONS, enabled: true }));
    await settle();
    expect(result.current).toEqual({ data: 1, loading: false, error: null, hasFetched: true });

    act(() => vi.advanceTimersByTime(INTERVAL_MS));
    await settle();
    expect(result.current.data).toBe(2);
  });

  it("無効な間は取りに行かず、初期値のまま「まだ取りに行っていない」", async () => {
    const fetcher = vi.fn(async () => 1);
    const { result } = renderHook(() => usePolledFetch(fetcher, 0, { ...OPTIONS, enabled: false }));
    await settle();
    act(() => vi.advanceTimersByTime(INTERVAL_MS * 3));
    expect(fetcher).not.toHaveBeenCalled();
    expect(result.current).toEqual({ data: 0, loading: false, error: null, hasFetched: false });
  });

  it("読み込み中を出すのは最初の1回だけ（定期の取り直しでは出さない）", async () => {
    const calls: ReturnType<typeof deferred<number>>[] = [];
    const fetcher = vi.fn(() => {
      const call = deferred<number>();
      calls.push(call);
      return call.promise;
    });
    const { result } = renderHook(() => usePolledFetch(fetcher, 0, { ...OPTIONS, enabled: true }));
    await settle();
    expect(result.current.loading).toBe(true);
    calls[0].resolve(1);
    await settle();
    expect(result.current.loading).toBe(false);

    act(() => vi.advanceTimersByTime(INTERVAL_MS));
    await settle();
    expect(calls).toHaveLength(2);
    expect(result.current.loading).toBe(false);
  });

  it("失敗は前回の値を残して文言だけを出し、警告として記録する。次に成功すれば文言を消す", async () => {
    let fail = false;
    const fetcher = vi.fn(async () => {
      if (fail) throw new Error("通信できません");
      return "値";
    });
    const { result } = renderHook(() =>
      usePolledFetch(fetcher, "", { ...OPTIONS, enabled: true, debugLogCategory: "api:test" }),
    );
    await settle();
    fail = true;
    act(() => vi.advanceTimersByTime(INTERVAL_MS));
    await settle();
    expect(result.current).toMatchObject({ data: "値", error: "通信できません" });
    expect(debugLog).toHaveBeenCalledWith(
      "api:test",
      "テスト対象の読み込みに失敗",
      { error: "通信できません" },
      "warn",
    );

    fail = false;
    act(() => vi.advanceTimersByTime(INTERVAL_MS));
    await settle();
    expect(result.current.error).toBeNull();
  });

  it("Errorでない失敗は、対象名から作った文言にする", async () => {
    const fetcher = vi.fn(() => Promise.reject("理由不明"));
    const { result } = renderHook(() => usePolledFetch(fetcher, 0, { ...OPTIONS, enabled: true }));
    await settle();
    expect(result.current.error).toBe("テスト対象の取得に失敗しました");
  });

  it("無効へ切り替えると「まだ取りに行っていない」へ戻り、取りかけの応答と以後の取り直しを捨てる", async () => {
    const pending = deferred<number>();
    const fetcher = vi.fn(async () => 1);
    const { result, rerender } = renderHook(({ enabled }) => usePolledFetch(fetcher, 0, { ...OPTIONS, enabled }), {
      initialProps: { enabled: true },
    });
    await settle();
    expect(result.current.hasFetched).toBe(true);

    fetcher.mockImplementationOnce(() => pending.promise);
    act(() => vi.advanceTimersByTime(INTERVAL_MS));
    rerender({ enabled: false });
    expect(result.current.hasFetched).toBe(false);

    pending.resolve(99);
    await settle();
    act(() => vi.advanceTimersByTime(INTERVAL_MS * 2));
    await settle();
    expect(result.current.data).toBe(1);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

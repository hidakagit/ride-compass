import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePolledFetch } from "./usePolledFetch";

// 改善計画T470: useDynamicWeatherLayers.tsに5箇所独立実装されていた「cancelledフラグ+
// Promise+catch」の同型フェッチ骨格を統合したusePolledFetch自体の単体テスト。
describe("usePolledFetch", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("マウント時に即座に1回フェッチし、成功結果をdataへ反映する", async () => {
    const fetcher = vi.fn().mockResolvedValue("result-1");

    const { result } = renderHook(() =>
      usePolledFetch(fetcher, "initial", { enabled: true, intervalMs: 100000, label: "テスト" }),
    );

    expect(result.current.data).toBe("initial");
    await waitFor(() => expect(result.current.data).toBe("result-1"));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBeNull();
  });

  it("enabled=falseの間はフェッチせず、初期値のまま", async () => {
    const fetcher = vi.fn().mockResolvedValue("result-1");

    renderHook(() => usePolledFetch(fetcher, "initial", { enabled: false, intervalMs: 100000, label: "テスト" }));

    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("失敗時はerrorへメッセージを記録し、dataは変化しない", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() =>
      usePolledFetch(fetcher, "initial", { enabled: true, intervalMs: 100000, label: "テスト" }),
    );

    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.data).toBe("initial");
  });

  it("Errorインスタンスでない失敗はlabelから組み立てた既定メッセージになる", async () => {
    const fetcher = vi.fn().mockRejectedValue("not-an-error");

    const { result } = renderHook(() =>
      usePolledFetch(fetcher, "initial", { enabled: true, intervalMs: 100000, label: "テスト対象" }),
    );

    await waitFor(() => expect(result.current.error).toBe("テスト対象の取得に失敗しました"));
  });

  it("失敗後に成功すると、errorがnullへ戻る", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce("result-1");

    vi.useFakeTimers();
    const { result } = renderHook(() =>
      usePolledFetch(fetcher, "initial", { enabled: true, intervalMs: 1000, label: "テスト" }),
    );

    await vi.waitFor(() => expect(result.current.error).toBe("boom"));

    await vi.advanceTimersByTimeAsync(1000);

    await vi.waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.data).toBe("result-1");
  });

  it("intervalMsごとに再フェッチする", async () => {
    const fetcher = vi.fn().mockResolvedValue("result");

    vi.useFakeTimers();
    renderHook(() => usePolledFetch(fetcher, "initial", { enabled: true, intervalMs: 1000, label: "テスト" }));

    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(1000);
    expect(fetcher).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(1000);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("loadingは初回フェッチの間だけtrueになり、2回目以降は変化しない", async () => {
    let resolveFirst: (value: string) => void = () => {};
    const first = new Promise<string>((resolve) => {
      resolveFirst = resolve;
    });
    const fetcher = vi.fn().mockReturnValueOnce(first).mockResolvedValue("later");

    vi.useFakeTimers();
    const { result } = renderHook(() =>
      usePolledFetch(fetcher, "initial", { enabled: true, intervalMs: 1000, label: "テスト" }),
    );

    await vi.waitFor(() => expect(result.current.loading).toBe(true));

    resolveFirst("result-1");
    await vi.waitFor(() => expect(result.current.loading).toBe(false));

    await vi.advanceTimersByTimeAsync(1000);
    // 2回目以降（ポーリング）はisFirstLoad=falseのためloadingは変化しない。
    expect(result.current.loading).toBe(false);
  });

  it("アンマウント後は古いフェッチの解決結果を反映しない", async () => {
    let resolveFetch: (value: string) => void = () => {};
    const fetcher = vi.fn().mockReturnValue(
      new Promise<string>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const { result, unmount } = renderHook(() =>
      usePolledFetch(fetcher, "initial", { enabled: true, intervalMs: 100000, label: "テスト" }),
    );

    unmount();
    resolveFetch("result-1");
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(result.current.data).toBe("initial");
  });
});

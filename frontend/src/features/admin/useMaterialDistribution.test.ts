/**
 * `useMaterialDistribution.ts`——材料1件の値の分布を取り、同じ材料は（取れなかったことも含めて）
 * 1回しか取りに行かないこと。
 *
 * 結果はモジュールの中で共有されるため、テストごとに別の材料idを使う。
 *
 * ここで見ないもの:
 * - 分布を画面にどう出すか → `AxisStudio/MaterialRangeHint.test.tsx`
 */
import { StrictMode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MaterialDistribution } from "./adminApi";

const api = vi.hoisted(() => ({ fetchMaterialDistribution: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);

import { useMaterialDistribution } from "./useMaterialDistribution";

function distribution(p50: number): MaterialDistribution {
  return { available: true, sample_ways: 1, total_km: 1, quantiles: { p50 }, bins: [], zero_share: 0 };
}

beforeEach(() => {
  api.fetchMaterialDistribution.mockReset();
});

describe("useMaterialDistribution", () => {
  it("材料が無ければ取りに行かない", async () => {
    const { result } = renderHook(() => useMaterialDistribution(undefined));
    await act(async () => {});
    expect(api.fetchMaterialDistribution).not.toHaveBeenCalled();
    expect(result.current).toEqual({ distribution: null, loading: false });
  });

  it("取っている間は読み込み中で、届いたら分布を返す", async () => {
    let resolve!: (value: MaterialDistribution) => void;
    api.fetchMaterialDistribution.mockReturnValue(new Promise<MaterialDistribution>((res) => (resolve = res)));
    const { result } = renderHook(() => useMaterialDistribution("m_loading"));

    await waitFor(() => expect(result.current.loading).toBe(true));
    await act(async () => resolve(distribution(5)));
    expect(result.current).toEqual({ distribution: distribution(5), loading: false });
  });

  it("同じ材料を別の場所が選んでも、取りに行くのは1回で、同じ分布を返す", async () => {
    api.fetchMaterialDistribution.mockResolvedValue(distribution(7));
    const first = renderHook(() => useMaterialDistribution("m_shared"));
    await waitFor(() => expect(first.result.current.distribution).toEqual(distribution(7)));

    const second = renderHook(() => useMaterialDistribution("m_shared"));
    await waitFor(() => expect(second.result.current.distribution).toEqual(distribution(7)));
    expect(api.fetchMaterialDistribution).toHaveBeenCalledTimes(1);
  });

  it("取れなかったら分布なしで返し、その材料を取り直さない", async () => {
    api.fetchMaterialDistribution.mockRejectedValue(new Error("分布の取得に失敗しました"));
    const first = renderHook(() => useMaterialDistribution("m_failing"));
    await waitFor(() => expect(api.fetchMaterialDistribution).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(first.result.current).toEqual({ distribution: null, loading: false }));

    const second = renderHook(() => useMaterialDistribution("m_failing"));
    await act(async () => {});
    expect(second.result.current).toEqual({ distribution: null, loading: false });
    expect(api.fetchMaterialDistribution).toHaveBeenCalledTimes(1);
  });

  it("立ち上げ直し（StrictModeの二重実行）でも、取りに行くのは1回", async () => {
    api.fetchMaterialDistribution.mockResolvedValue(distribution(4));
    const { result } = renderHook(() => useMaterialDistribution("m_strict"), { wrapper: StrictMode });
    await waitFor(() => expect(result.current.distribution).toEqual(distribution(4)));
    expect(api.fetchMaterialDistribution).toHaveBeenCalledTimes(1);
  });

  it("材料を切り替えたら、前の材料の取得が後から失敗しても今の分布を消さない", async () => {
    let failFirst!: (reason: unknown) => void;
    api.fetchMaterialDistribution
      .mockReturnValueOnce(new Promise<MaterialDistribution>((_resolve, reject) => (failFirst = reject)))
      .mockResolvedValueOnce(distribution(3));
    const { result, rerender } = renderHook(({ id }) => useMaterialDistribution(id), {
      initialProps: { id: "m_old_failing" },
    });
    await waitFor(() => expect(api.fetchMaterialDistribution).toHaveBeenCalledTimes(1));

    rerender({ id: "m_new_after_failing" });
    await waitFor(() => expect(result.current.distribution).toEqual(distribution(3)));
    await act(async () => failFirst(new Error("遅れた失敗")));
    expect(result.current).toEqual({ distribution: distribution(3), loading: false });
  });

  it("材料を切り替えたら、後から届いた前の材料の分布を出さない", async () => {
    let answerFirst!: (value: MaterialDistribution) => void;
    api.fetchMaterialDistribution
      .mockReturnValueOnce(new Promise<MaterialDistribution>((resolve) => (answerFirst = resolve)))
      .mockResolvedValueOnce(distribution(2));
    const { result, rerender } = renderHook(({ id }) => useMaterialDistribution(id), {
      initialProps: { id: "m_old" },
    });
    await waitFor(() => expect(api.fetchMaterialDistribution).toHaveBeenCalledTimes(1));

    rerender({ id: "m_new" });
    await waitFor(() => expect(result.current.distribution).toEqual(distribution(2)));
    await act(async () => answerFirst(distribution(99)));
    expect(result.current.distribution).toEqual(distribution(2));
  });
});

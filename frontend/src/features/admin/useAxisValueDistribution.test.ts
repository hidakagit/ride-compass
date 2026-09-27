/**
 * `useAxisValueDistribution.ts`——編集中の点数の形で生値の分布を取り、取り直すのは「分布の形を決める部分」
 * （`termsKey`）が変わったときだけにすること。折れ点だけを動かしている間は通信しない。
 *
 * 待ちの長さ（落ち着くまで遅らせること）は `hooks/useDebouncedValue` の持ち物なので、ここでは即時にする。
 *
 * ここで見ないもの:
 * - 分布へ折れ点を当てはめること → `AxisStudio/scoreDistribution.test.ts`
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AxisShape } from "@/types/route";
import type { ValueDistribution } from "./AxisStudio/scoreDistribution";

const api = vi.hoisted(() => ({ fetchAxisValueDistribution: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);
vi.mock("@/hooks/useDebouncedValue", () => ({ MAP_FETCH_DEBOUNCE_MS: 0, useDebouncedValue: <T>(value: T) => value }));

import { useAxisValueDistribution } from "./useAxisValueDistribution";

/** 折れ点の位置だけが違う形。 */
function shape(breakpoint: number): AxisShape {
  return { kind: "breakpoint_linear", terms: [], preprocess: "identity", breakpoints: [[breakpoint, 0]] };
}

function distribution(sampleWays: number): ValueDistribution {
  return { sample_ways: sampleWays, total_km: 1, quantiles: {}, bins: [], zero_share: 0 };
}

interface Props {
  enabled: boolean;
  termsKey: string;
  shape: AxisShape;
}

function renderDistribution(initialProps: Props) {
  return renderHook(({ enabled, termsKey, shape }: Props) => useAxisValueDistribution(enabled, termsKey, () => shape), {
    initialProps,
  });
}

beforeEach(() => {
  api.fetchAxisValueDistribution.mockReset();
});

describe("useAxisValueDistribution", () => {
  it.each([
    ["使わない", { enabled: false, termsKey: "k", shape: shape(0) }],
    ["形を決める部分が空", { enabled: true, termsKey: "", shape: shape(0) }],
  ])("%sときは取りに行かず、分布なし", async (_case, props) => {
    const { result } = renderDistribution(props);
    await act(async () => {});
    expect(api.fetchAxisValueDistribution).not.toHaveBeenCalled();
    expect(result.current).toEqual({ distribution: null, loading: false, error: null });
  });

  it("取っている間は読み込み中で、届いたら分布を返す。送るのは今の形", async () => {
    let resolve!: (value: ValueDistribution) => void;
    api.fetchAxisValueDistribution.mockReturnValue(new Promise<ValueDistribution>((res) => (resolve = res)));
    const { result } = renderDistribution({ enabled: true, termsKey: "k1", shape: shape(1) });

    await waitFor(() => expect(result.current.loading).toBe(true));
    expect(api.fetchAxisValueDistribution).toHaveBeenCalledWith(shape(1));
    resolve(distribution(3));
    await waitFor(() => expect(result.current).toEqual({ distribution: distribution(3), loading: false, error: null }));
  });

  it("形を決める部分が変わらなければ、形（折れ点）が変わっても取り直さない。変われば取り直す", async () => {
    api.fetchAxisValueDistribution.mockResolvedValue(distribution(1));
    const { result, rerender } = renderDistribution({ enabled: true, termsKey: "k1", shape: shape(1) });
    await waitFor(() => expect(result.current.distribution).toEqual(distribution(1)));

    rerender({ enabled: true, termsKey: "k1", shape: shape(2) });
    await act(async () => {});
    expect(api.fetchAxisValueDistribution).toHaveBeenCalledTimes(1);

    rerender({ enabled: true, termsKey: "k2", shape: shape(3) });
    await waitFor(() => expect(api.fetchAxisValueDistribution).toHaveBeenCalledTimes(2));
    expect(api.fetchAxisValueDistribution).toHaveBeenLastCalledWith(shape(3));
  });

  it("取り直している間は、前の分布を出したまま読み込み中にする", async () => {
    let resolveSecond!: (value: ValueDistribution) => void;
    api.fetchAxisValueDistribution
      .mockResolvedValueOnce(distribution(1))
      .mockReturnValueOnce(new Promise<ValueDistribution>((resolve) => (resolveSecond = resolve)));
    const { result, rerender } = renderDistribution({ enabled: true, termsKey: "k1", shape: shape(0) });
    await waitFor(() => expect(result.current.distribution).toEqual(distribution(1)));

    rerender({ enabled: true, termsKey: "k2", shape: shape(0) });
    await waitFor(() => expect(result.current).toEqual({ distribution: distribution(1), loading: true, error: null }));
    resolveSecond(distribution(2));
    await waitFor(() => expect(result.current).toEqual({ distribution: distribution(2), loading: false, error: null }));
  });

  it.each([
    ["Error", new Error("分布の解析に失敗しました"), "分布の解析に失敗しました"],
    ["Error以外", "timeout", "分布の取得に失敗しました"],
  ])("%sで失敗したら、分布なしで理由を返す", async (_kind, reason, message) => {
    api.fetchAxisValueDistribution.mockRejectedValue(reason);
    const { result } = renderDistribution({ enabled: true, termsKey: "k", shape: shape(0) });
    await waitFor(() => expect(result.current).toEqual({ distribution: null, loading: false, error: message }));
  });

  it("使わなくなったら、分布を消す", async () => {
    api.fetchAxisValueDistribution.mockResolvedValue(distribution(1));
    const { result, rerender } = renderDistribution({ enabled: true, termsKey: "k", shape: shape(0) });
    await waitFor(() => expect(result.current.distribution).toEqual(distribution(1)));

    rerender({ enabled: false, termsKey: "k", shape: shape(0) });
    await waitFor(() => expect(result.current.distribution).toBeNull());
  });
});

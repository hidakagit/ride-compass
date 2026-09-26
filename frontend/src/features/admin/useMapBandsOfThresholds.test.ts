/**
 * `useMapBandsOfThresholds.ts`——しきい値を上書きしている間だけ、地図で段にならない境界と地図に残る段を
 * backendに問い、判定できないとき・入力を変えた直後は「判定なし」を返すこと。
 *
 * 待ちの長さ（落ち着くまで遅らせること）は `hooks/useDebouncedValue` の持ち物なので、ここでは即時にする。
 *
 * ここで見ないもの:
 * - 判定の結果を画面にどう出すか → `AxisStudio/AxisMapDisplaySection.test.tsx`
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DisplayThresholdsPreviewRequest, MapBandsOfThresholds } from "./adminApi";

const api = vi.hoisted(() => ({ fetchMapBandsOfThresholds: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);
vi.mock("@/hooks/useDebouncedValue", () => ({ MAP_FETCH_DEBOUNCE_MS: 0, useDebouncedValue: <T>(value: T) => value }));

import { NO_MAP_BANDS_JUDGEMENT, useMapBandsOfThresholds } from "./useMapBandsOfThresholds";

function request(thresholds: number[]): DisplayThresholdsPreviewRequest {
  return { axis_id: "axis_a", shape: { kind: "categorical", material: "m", mapping: {} }, thresholds };
}

const judged: MapBandsOfThresholds = { droppedOnMap: [2], bandsOnMap: [0, 2] };

beforeEach(() => {
  api.fetchMapBandsOfThresholds.mockReset();
});

describe("useMapBandsOfThresholds", () => {
  it("しきい値を上書きしていない間は問い合わせず、判定なし", async () => {
    const { result } = renderHook(() => useMapBandsOfThresholds(null));
    await act(async () => {});
    expect(api.fetchMapBandsOfThresholds).not.toHaveBeenCalled();
    expect(result.current).toEqual(NO_MAP_BANDS_JUDGEMENT);
  });

  it("下書きの形・しきい値をそのまま問い、答えを返す", async () => {
    api.fetchMapBandsOfThresholds.mockResolvedValue(judged);
    const { result } = renderHook(() => useMapBandsOfThresholds(request([1, 2])));

    await waitFor(() => expect(result.current).toEqual(judged));
    expect(api.fetchMapBandsOfThresholds).toHaveBeenCalledWith(request([1, 2]));
  });

  it("判定に失敗したら、判定なし（効かない値がある、とは言わない）", async () => {
    api.fetchMapBandsOfThresholds.mockRejectedValue(new Error("しきい値の確認に失敗しました"));
    const { result } = renderHook(() => useMapBandsOfThresholds(request([1])));
    await waitFor(() => expect(api.fetchMapBandsOfThresholds).toHaveBeenCalledTimes(1));
    await act(async () => {});
    expect(result.current).toEqual(NO_MAP_BANDS_JUDGEMENT);
  });

  it("入力を変えた直後は、前の入力の答えを返さない", async () => {
    let answerSecond!: (value: MapBandsOfThresholds) => void;
    api.fetchMapBandsOfThresholds
      .mockResolvedValueOnce(judged)
      .mockReturnValueOnce(new Promise<MapBandsOfThresholds>((resolve) => (answerSecond = resolve)));
    const { result, rerender } = renderHook(({ thresholds }) => useMapBandsOfThresholds(request(thresholds)), {
      initialProps: { thresholds: [1, 2] },
    });
    await waitFor(() => expect(result.current).toEqual(judged));

    rerender({ thresholds: [1, 3] });
    expect(result.current).toEqual(NO_MAP_BANDS_JUDGEMENT);
    answerSecond({ droppedOnMap: [], bandsOnMap: [0, 1, 2] });
    await waitFor(() => expect(result.current.bandsOnMap).toEqual([0, 1, 2]));
  });
});

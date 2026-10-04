/**
 * `useMapBandsOfThresholds.ts`——しきい値を上書きしている間だけ、地図で段にならない境界と地図に残る段を
 * backendに問い、判定できないとき・入力を変えた直後は「判定なし」を返すこと（判定できなかったときは、そのことも返す）。
 *
 * 待ちの長さ（落ち着くまで遅らせること）は `hooks/useDebouncedValue` の持ち物なので、ここでは即時にする。
 *
 * ここで見ないもの:
 * - 判定の結果を画面にどう出すか → `AxisStudio/AxisMapDisplaySection.test.tsx`
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { heldReplies, onSameOrigin } from "@/testing/backendServer";

import type { DisplayThresholdsPreviewRequest } from "./adminApi";

vi.mock("@/hooks/useDebouncedValue", () => ({ MAP_FETCH_DEBOUNCE_MS: 0, useDebouncedValue: <T>(value: T) => value }));

import { useMapBandsOfThresholds } from "./useMapBandsOfThresholds";

const PREVIEW = "/admin/api/axis-definitions/preview-display-thresholds";

function request(thresholds: number[]): DisplayThresholdsPreviewRequest {
  return { axis_id: "axis_a", shape: { kind: "categorical", material: "m", mapping: {} }, thresholds };
}

const judgement = (droppedOnMap: number[], bandsOnMap: number[]) =>
  Response.json({ dropped_on_map: droppedOnMap, bands_on_map: bandsOnMap });
const judgedOk = { droppedOnMap: [2], bandsOnMap: [0, 2], failed: false };
/** 判定が無い間: 落ちる値なし・全段が残る（入力どおりの段で出す）。 */
const noJudgement = { droppedOnMap: [], bandsOnMap: null, failed: false };

describe("useMapBandsOfThresholds", () => {
  it("しきい値を上書きしていない間は問い合わせず、判定なし", async () => {
    const { result } = renderHook(() => useMapBandsOfThresholds(null));
    await act(async () => {});
    expect(result.current).toEqual(noJudgement);
  });

  it("下書きを問い、答えを返す", async () => {
    onSameOrigin("POST", PREVIEW, () => judgement([2], [0, 2]));
    const { result } = renderHook(() => useMapBandsOfThresholds(request([1, 2])));

    await waitFor(() => expect(result.current).toEqual(judgedOk));
  });

  it("判定に失敗したら、判定なし（効かない値がある、とは言わない）で、失敗したことを返す", async () => {
    onSameOrigin("POST", PREVIEW, () => new Response(null, { status: 500 }));
    const { result } = renderHook(() => useMapBandsOfThresholds(request([1])));
    await waitFor(() => expect(result.current).toEqual({ ...noJudgement, failed: true }));
  });

  it("入力を変えた直後は、前の入力の答えを返さない", async () => {
    const held = heldReplies();
    onSameOrigin("POST", PREVIEW, ({ body }) =>
      (body as DisplayThresholdsPreviewRequest).thresholds?.[1] === 2 ? judgement([2], [0, 2]) : held.reply(),
    );
    const { result, rerender } = renderHook(({ thresholds }) => useMapBandsOfThresholds(request(thresholds)), {
      initialProps: { thresholds: [1, 2] },
    });
    await waitFor(() => expect(result.current).toEqual(judgedOk));

    rerender({ thresholds: [1, 3] });
    expect(result.current).toEqual(noJudgement);
    await held.answer(0, judgement([], [0, 1, 2]));
    await waitFor(() => expect(result.current.bandsOnMap).toEqual([0, 1, 2]));
  });
});

// @vitest-environment node
/**
 * `axisPreviewApi.ts`——しきい値の判定の応答を、画面が読む形へ写すこと。
 *
 * ここで見ないもの:
 * - 叩く口・待ち時間・本文の項目名 → `adminApiClients.test.ts`
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchMapBandsOfThresholds } from "./axisPreviewApi";

afterEach(() => {
  vi.unstubAllGlobals();
});

function respondWith(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })),
  );
}

const request = {
  axis_id: "axis_a",
  shape: { kind: "categorical" as const, material: "m", mapping: {} },
  thresholds: [1, 2],
};

describe("fetchMapBandsOfThresholds", () => {
  it("地図で段にならない境界と、地図の各段が入力のどの段に当たるかを返す", async () => {
    respondWith({ dropped_on_map: [2], bands_on_map: [0, 2] });

    await expect(fetchMapBandsOfThresholds(request)).resolves.toEqual({ droppedOnMap: [2], bandsOnMap: [0, 2] });
  });
});

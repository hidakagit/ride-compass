// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeResponse } from "@/testing/fetchMocks";

import { jmaDelivery } from "./jmaNowcastFrames";
import { fetchLidenGeojson, LIDEN_MARK_VALUE_PROPERTY } from "./lidenLayer";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchLidenGeojson（そのコマの落雷地点）", () => {
  const frame = { basetime: "20260924001000", validtime: "20260924001000", isForecast: false };

  it("そのコマの要素配下のGeoJSONを取り、どの地点にも記号の大きさを決める値を足す（元の属性は残す）", async () => {
    const liden = jmaDelivery("disaster/liden");
    const fetchMock = vi.fn<(url: string) => Promise<ReturnType<typeof makeResponse>>>(async () =>
      makeResponse({
        json: async () => ({
          type: "FeatureCollection",
          features: [
            { type: "Feature", geometry: { type: "Point", coordinates: [139, 35] }, properties: { type: 1 } },
            { type: "Feature", geometry: { type: "Point", coordinates: [140, 36] }, properties: null },
          ],
        }),
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const geojson = await fetchLidenGeojson(frame);
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/jma-tile/bosai/jmatile/data/${liden.pathGroup}/20260924001000/none/20260924001000/surf/${liden.id}/data.geojson?id=${liden.id}`,
    );
    expect(geojson.features.map((feature) => feature.properties)).toEqual([
      { type: 1, [LIDEN_MARK_VALUE_PROPERTY]: 1 },
      { [LIDEN_MARK_VALUE_PROPERTY]: 1 },
    ]);
  });

  it("取得の失敗はそのまま投げる（表示しないかは呼び出し側が決める）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => makeResponse({ ok: false, status: 503 })),
    );
    await expect(fetchLidenGeojson(frame)).rejects.toThrow("雷放電位置データ");
  });
});

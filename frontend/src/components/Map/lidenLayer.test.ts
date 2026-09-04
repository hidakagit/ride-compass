// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchLidenFrames, fetchLidenGeojson, lidenFrames, LIDEN_MARK_VALUE_PROPERTY } from "./lidenLayer";

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body, headers: new Headers() };
}

// targetTimes_N3.jsonはliden自体は5分おきの全エントリに存在する（thns/trnsは10分おきの
// エントリにしか無い、thunderNowcast.test.tsのN3_WITH_LIDEN_ONLY_GAPと対になる構造）。
const N3 = [
  { basetime: "20260822055500", validtime: "20260822055500", elements: ["thns", "trns", "liden"] },
  { basetime: "20260822060000", validtime: "20260822060000", elements: ["liden"] },
  { basetime: "20260822060500", validtime: "20260822060500", elements: ["thns", "trns", "liden"] },
];

describe("lidenLayer（改善計画T541）", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchLidenFramesはelementsにlidenを含む全エントリをvalidtime昇順で返す（thns/trns専用エントリへの絞り込みはしない）", async () => {
    let requestedUrl = "";
    const fetchMock = vi.fn((url: string) => {
      requestedUrl = url;
      return Promise.resolve(jsonResponse(N3));
    });
    vi.stubGlobal("fetch", fetchMock);

    const frames = await fetchLidenFrames();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestedUrl).toContain("targetTimes_N3.json");
    expect(frames.map((f) => f.validtime)).toEqual(["20260822055500", "20260822060000", "20260822060500"]);
  });

  it("elementsにlidenを含まないエントリは除外する", async () => {
    const withGap = [...N3, { basetime: "20260822061000", validtime: "20260822061000", elements: ["thns", "trns"] }];
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(withGap))));

    const frames = await fetchLidenFrames();

    expect(frames.map((f) => f.validtime)).not.toContain("20260822061000");
  });

  it("取得に失敗した場合は例外を投げる", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(null, false, 500))));
    await expect(fetchLidenFrames()).rejects.toThrow();
  });

  describe("lidenFrames", () => {
    it("フレーム列をdynamicWeather.tsの共通フレーム列（refはindex）へ変換する", () => {
      const frames = [
        { basetime: "20260822055500", validtime: "20260822055500", isForecast: false },
        { basetime: "20260822060000", validtime: "20260822060000", isForecast: false },
      ];
      const result = lidenFrames(frames);
      expect(result).toHaveLength(2);
      expect(result[0].ref).toBe(0);
      expect(result[1].ref).toBe(1);
      expect(result[0].time.toISOString()).toBe("2026-08-22T05:55:00.000Z");
    });
  });

  describe("fetchLidenGeojson", () => {
    const frames = [{ basetime: "20260822055500", validtime: "20260822055500", isForecast: false }];

    it("basetime/validtime/id=lidenを組み立てたURLへfetchし、各featureへvalueプロパティを合成する", async () => {
      let requestedUrl = "";
      const geojson = {
        type: "FeatureCollection",
        features: [
          { type: "Feature", geometry: { type: "Point", coordinates: [139.7, 35.7] }, properties: { id: "a", type: 1 } },
        ],
      };
      vi.stubGlobal(
        "fetch",
        vi.fn((url: string) => {
          requestedUrl = url;
          return Promise.resolve(jsonResponse(geojson));
        })
      );

      const result = await fetchLidenGeojson(frames, 0);

      expect(requestedUrl).toBe(
        "/api/jma-tile/bosai/jmatile/data/nowc/20260822055500/none/20260822055500/surf/liden/data.geojson?id=liden"
      );
      expect(result?.features[0].properties).toEqual({ id: "a", type: 1, [LIDEN_MARK_VALUE_PROPERTY]: 1 });
    });

    it("範囲外のrefに対してはundefinedを返す（fetch自体を行わない）", async () => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);

      const result = await fetchLidenGeojson(frames, 5);

      expect(result).toBeUndefined();
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });
});

// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchThunderNowcastFrames,
  thunderFrames,
  thunderRenderPayload,
  tornadoRenderPayload,
  THUNDER_ACTIVITY_LEVELS,
  TORNADO_POTENTIAL_LEVELS,
} from "./thunderNowcast";

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

// 実機確認（2026-08-22）で得た実際のtargetTimes_N3.json構造を模したフィクスチャ:
// 古いbasetimeの行はvalidtime===basetime（実況のみ）、最新basetimeの行だけ
// validtime>basetimeの予測が複数並ぶ。
const N3 = [
  { basetime: "20260822055500", validtime: "20260822055500", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
  { basetime: "20260822060000", validtime: "20260822060000", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
  { basetime: "20260822085000", validtime: "20260822085000", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
  { basetime: "20260822085000", validtime: "20260822090000", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
  { basetime: "20260822085000", validtime: "20260822091000", elements: ["thns", "thns_nd", "trns", "trns_nd"] },
];

describe("thunderNowcast（改善計画T204）", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchThunderNowcastFramesはtargetTimes_N3.json 1本からvalidtime昇順のフレーム列を返し、isForecastをvalidtime>basetimeで判定する", async () => {
    let requestedUrl = "";
    const fetchMock = vi.fn((url: string) => {
      requestedUrl = url;
      return Promise.resolve(jsonResponse(N3));
    });
    vi.stubGlobal("fetch", fetchMock);

    const frames = await fetchThunderNowcastFrames();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestedUrl).toContain("targetTimes_N3.json");
    expect(frames.map((f) => f.validtime)).toEqual([
      "20260822055500",
      "20260822060000",
      "20260822085000",
      "20260822090000",
      "20260822091000",
    ]);
    expect(frames.map((f) => f.isForecast)).toEqual([false, false, false, true, true]);
  });

  it("取得に失敗した場合は例外を投げる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse(null, false, 500)))
    );
    await expect(fetchThunderNowcastFrames()).rejects.toThrow();
  });

  describe("thunderFrames", () => {
    it("フレーム列をdynamicWeather.tsの共通フレーム列（refはindex）へ変換する", () => {
      const frames = [
        { basetime: "20260822085000", validtime: "20260822085000", isForecast: false },
        { basetime: "20260822085000", validtime: "20260822090000", isForecast: true },
      ];
      const result = thunderFrames(frames);
      expect(result).toHaveLength(2);
      expect(result[0].ref).toBe(0);
      expect(result[1].ref).toBe(1);
      expect(result[0].time.toISOString()).toBe("2026-08-22T08:50:00.000Z");
    });
  });

  describe("thunderRenderPayload / tornadoRenderPayload", () => {
    const frames = [{ basetime: "20260822085000", validtime: "20260822090000", isForecast: true }];

    it("thunderRenderPayloadはプロダクトコードthnsのrasterTileペイロードを返す", () => {
      const payload = thunderRenderPayload(frames, 0);
      expect(payload).toEqual({
        kind: "rasterTile",
        tileUrlTemplate: "https://www.jma.go.jp/bosai/jmatile/data/nowc/20260822085000/none/20260822090000/surf/thns/{z}/{x}/{y}.png",
      });
    });

    it("tornadoRenderPayloadはプロダクトコードtrnsのrasterTileペイロードを返す（同じフレーム・同じref）", () => {
      const payload = tornadoRenderPayload(frames, 0);
      expect(payload).toEqual({
        kind: "rasterTile",
        tileUrlTemplate: "https://www.jma.go.jp/bosai/jmatile/data/nowc/20260822085000/none/20260822090000/surf/trns/{z}/{x}/{y}.png",
      });
    });

    it("範囲外のrefに対してはundefinedを返す（1点の欠損で表示全体を落とさない）", () => {
      expect(thunderRenderPayload(frames, 5)).toBeUndefined();
      expect(tornadoRenderPayload(frames, 5)).toBeUndefined();
    });
  });

  describe("凡例", () => {
    it("THUNDER_ACTIVITY_LEVELSは活動度1〜4の4段階を持つ", () => {
      expect(THUNDER_ACTIVITY_LEVELS).toHaveLength(4);
      expect(THUNDER_ACTIVITY_LEVELS.map((l) => l.key)).toEqual(["level1", "level2", "level3", "level4"]);
    });

    it("TORNADO_POTENTIAL_LEVELSは発生確度1・2の2段階を持つ", () => {
      expect(TORNADO_POTENTIAL_LEVELS).toHaveLength(2);
      expect(TORNADO_POTENTIAL_LEVELS.map((l) => l.key)).toEqual(["potential1", "potential2"]);
    });
  });
});

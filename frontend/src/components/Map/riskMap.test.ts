// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchCurrentRiskFrames,
  fetchLinearRainbandFrames,
  heavyRainRenderPayload,
  inundationRenderPayload,
  landRenderPayload,
  linearRainbandRenderPayload,
  RISK_LEVEL_COLORS,
} from "./riskMap";
import { parseValidtime } from "./jmaNowcastFrames";

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body, headers: new Headers() };
}

describe("riskMap（改善計画T410: キキクル+線状降水帯予測マップ）", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("fetchCurrentRiskFrames（キキクル: 土砂・大雨・浸水）", () => {
    it("各要素の最新basetimeを1件だけ選び、DynamicWeatherFrameへ変換する", async () => {
      const raw = [
        { basetime: "20260829160000", validtime: "20260829160000", member: "immed1", elements: ["land", "inund"] },
        { basetime: "20260829170000", validtime: "20260829170000", member: "immed0", elements: ["land", "rain_mesh", "inund"] },
        { basetime: "20260829165000", validtime: "20260829165000", member: "immed2", elements: ["rain_mesh"] },
      ];
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(raw))));

      const frames = await fetchCurrentRiskFrames();

      expect(frames.land).toEqual([
        { time: parseValidtime("20260829170000"), ref: raw[1] },
      ]);
      expect(frames.heavyRain).toEqual([
        { time: parseValidtime("20260829170000"), ref: raw[1] },
      ]);
      expect(frames.inundation).toEqual([
        { time: parseValidtime("20260829170000"), ref: raw[1] },
      ]);
    });

    it("対象の要素を含む行が無ければ空配列を返す", async () => {
      const raw = [{ basetime: "20260829170000", validtime: "20260829170000", member: "immed0", elements: ["land"] }];
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(raw))));

      const frames = await fetchCurrentRiskFrames();

      expect(frames.heavyRain).toEqual([]);
      expect(frames.inundation).toEqual([]);
    });

    it("取得に失敗した場合は例外を投げる", async () => {
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(null, false, 500))));

      await expect(fetchCurrentRiskFrames()).rejects.toThrow();
    });

    it("応答が配列でなければ例外を投げる", async () => {
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse({ not: "an array" }))));

      await expect(fetchCurrentRiskFrames()).rejects.toThrow();
    });
  });

  describe("fetchLinearRainbandFrames（線状降水帯予測マップ、rasrfのtargetTimes.json由来）", () => {
    it("elementsにsjfcstmapを含む最新の1件を返す", async () => {
      const raw = [
        { basetime: "20260829160000", validtime: "20260829160000", member: "none", elements: ["sjfcstmap"] },
        { basetime: "20260829165000", validtime: "20260829165000", member: "none", elements: ["sjfcstmap"] },
        // rasrf搭載行（sjfcstmapを持たないため対象外）。
        { basetime: "20260829163000", validtime: "20260829173000", member: "immed", elements: ["rasrf"] },
      ];
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(raw))));

      const frames = await fetchLinearRainbandFrames();

      expect(frames).toEqual([{ time: parseValidtime("20260829165000"), ref: raw[1] }]);
    });

    it("sjfcstmapを含む行が無ければ空配列を返す", async () => {
      const raw = [{ basetime: "20260829160000", validtime: "20260829160000", member: "immed", elements: ["rasrf"] }];
      vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(raw))));

      expect(await fetchLinearRainbandFrames()).toEqual([]);
    });
  });

  describe("render payload関数（タイルURLの組み立て）", () => {
    const ref = { basetime: "20260829170000", validtime: "20260829170000", member: "immed0" };

    it("landRenderPayloadはrisk/{basetime}/{member}/{validtime}/surf/land/... を返す", () => {
      expect(landRenderPayload(ref)).toEqual({
        kind: "rasterTile",
        tileUrlTemplate: "https://www.jma.go.jp/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/{z}/{x}/{y}.png",
      });
    });

    it("heavyRainRenderPayloadは要素コードrain_mesh（imageType定義に準拠）を使う", () => {
      expect(heavyRainRenderPayload(ref)).toEqual({
        kind: "rasterTile",
        tileUrlTemplate:
          "https://www.jma.go.jp/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/rain_mesh/{z}/{x}/{y}.png",
      });
    });

    it("inundationRenderPayloadは要素コードinundを使う", () => {
      expect(inundationRenderPayload(ref)).toEqual({
        kind: "rasterTile",
        tileUrlTemplate: "https://www.jma.go.jp/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/inund/{z}/{x}/{y}.png",
      });
    });

    it("linearRainbandRenderPayloadはrasrfグループ・要素コードsjfcstmapを使う", () => {
      const sjfcstRef = { basetime: "20260829165000", validtime: "20260829165000", member: "none" };
      expect(linearRainbandRenderPayload(sjfcstRef)).toEqual({
        kind: "rasterTile",
        tileUrlTemplate:
          "https://www.jma.go.jp/bosai/jmatile/data/rasrf/20260829165000/none/20260829165000/surf/sjfcstmap/{z}/{x}/{y}.png",
      });
    });
  });

  describe("RISK_LEVEL_COLORS", () => {
    it("平常(白)から災害切迫(黒)まで5段階を持つ", () => {
      expect(RISK_LEVEL_COLORS).toHaveLength(5);
      expect(RISK_LEVEL_COLORS[0].color).toBe("#ffffff");
      expect(RISK_LEVEL_COLORS.at(-1)?.color).toBe("#0c000c");
    });
  });
});

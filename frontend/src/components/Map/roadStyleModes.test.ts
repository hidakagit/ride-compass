import { describe, expect, it } from "vitest";
import { buildLegendFilterExpression } from "./legendFilter";
import {
  DEFAULT_ROAD_STYLE_MODE_ID,
  ROAD_STYLE_MODES,
  getRoadStyleMode,
  isRoadStyleModeId,
} from "./roadStyleModes";

describe("roadStyleModes", () => {
  it("3つのモード（舗装/未舗装・路面の種類・道路の種類）を定義している", () => {
    expect(ROAD_STYLE_MODES.map((m) => m.id)).toEqual(["paved", "surface", "highway"]);
    expect(DEFAULT_ROAD_STYLE_MODE_ID).toBe("paved");
  });

  it("各モードは凡例と色式を持ち、凡例の色・キーに重複がない（見分けられる配色）", () => {
    for (const mode of ROAD_STYLE_MODES) {
      expect(mode.legend.length).toBeGreaterThanOrEqual(3);
      expect(mode.colorExpression.length).toBeGreaterThan(0);
      const colors = mode.legend.map((entry) => entry.color);
      expect(new Set(colors).size).toBe(colors.length);
      const keys = mode.legend.map((entry) => entry.key);
      expect(new Set(keys).size).toBe(keys.length);
    }
  });

  it("surface/highwayモードはmatch式で、プロパティ欠落・未知タグ時のフォールバック色（グレー）を末尾に持つ", () => {
    for (const id of ["surface", "highway"] as const) {
      const mode = getRoadStyleMode(id);
      expect(mode.colorExpression[0]).toBe("match");
      // プロパティ欠落（null）をmatchへ直接渡さないようcoalesceで空文字へ倒す
      expect(mode.colorExpression[1]).toEqual(["coalesce", ["get", id], ""]);
      expect(mode.colorExpression[mode.colorExpression.length - 1]).toBe("#9ca3af");
    }
  });

  it("凡例の色と色式に出てくる色が一致する（凡例に無い色で描画されない）", () => {
    for (const mode of ROAD_STYLE_MODES) {
      const legendColors = new Set(mode.legend.map((entry) => entry.color));
      const expressionColors = mode.colorExpression.filter(
        (item): item is string => typeof item === "string" && item.startsWith("#"),
      );
      for (const color of expressionColors) {
        expect(legendColors.has(color)).toBe(true);
      }
    }
  });

  it("isRoadStyleModeIdは既知のIDのみtrue（localStorageの旧値・壊れた値を弾く）", () => {
    expect(isRoadStyleModeId("paved")).toBe(true);
    expect(isRoadStyleModeId("surface")).toBe(true);
    expect(isRoadStyleModeId("highway")).toBe(true);
    expect(isRoadStyleModeId("slope")).toBe(false); // 地域勾配モードは廃止済み（ルートレイヤーへ移設）
    expect(isRoadStyleModeId("")).toBe(false);
    expect(isRoadStyleModeId(null)).toBe(false);
  });

  describe("buildLegendFilterExpression（路面モードの凡例）", () => {
    it("非表示カテゴリが無ければnull（フィルタ解除）", () => {
      expect(buildLegendFilterExpression(getRoadStyleMode("paved").legend, [])).toBeNull();
    });

    it("非表示カテゴリの述語を否定してallで束ねる", () => {
      const filter = buildLegendFilterExpression(getRoadStyleMode("paved").legend, ["bad", "unknown"]);

      expect(filter).toEqual([
        "all",
        ["!", ["==", ["get", "surface_good"], false]],
        ["!", ["==", ["get", "surface_good"], null]],
      ]);
    });

    it("未知のキー（モード切替や定義変更の残骸）は無視する", () => {
      expect(buildLegendFilterExpression(getRoadStyleMode("paved").legend, ["no-such-key"])).toBeNull();
    });

    it("全モードの全凡例キーがフィルタ述語を持つ", () => {
      for (const mode of ROAD_STYLE_MODES) {
        for (const entry of mode.legend) {
          const filter = buildLegendFilterExpression(mode.legend, [entry.key]);
          expect(filter).toEqual(["all", ["!", entry.filter]]);
        }
      }
    });
  });
});

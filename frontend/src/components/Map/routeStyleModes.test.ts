import { describe, expect, it } from "vitest";
import { buildLegendFilterExpression } from "./legendFilter";
import {
  DEFAULT_ROUTE_STYLE_MODE_ID,
  ROUTE_STYLE_MODES,
  getRouteStyleMode,
  isRouteStyleModeId,
} from "./routeStyleModes";

describe("routeStyleModes", () => {
  it("2つのモード（風の影響・勾配）を定義し、デフォルトは風", () => {
    expect(ROUTE_STYLE_MODES.map((m) => m.id)).toEqual(["wind", "gradient"]);
    expect(DEFAULT_ROUTE_STYLE_MODE_ID).toBe("wind");
  });

  it("各モードは凡例と色式を持ち、凡例の色・キーに重複がなく、データなしカテゴリを含む", () => {
    for (const mode of ROUTE_STYLE_MODES) {
      expect(mode.colorExpression.length).toBeGreaterThan(0);
      const colors = mode.legend.map((entry) => entry.color);
      expect(new Set(colors).size).toBe(colors.length);
      const keys = mode.legend.map((entry) => entry.key);
      expect(new Set(keys).size).toBe(keys.length);
      expect(keys).toContain("nodata");
    }
  });

  it("データ欠落（プロパティnull）はグレーへ倒してからstep式で色分けする（to-numberのnull→0変換対策）", () => {
    const wind = getRouteStyleMode("wind");
    expect(wind.colorExpression[0]).toBe("case");
    expect(wind.colorExpression[1]).toEqual(["==", ["get", "wind_difficulty"], null]);
    expect(wind.colorExpression[2]).toBe("#9ca3af");
    expect((wind.colorExpression[3] as unknown[])[0]).toBe("step");

    const gradient = getRouteStyleMode("gradient");
    expect(gradient.colorExpression[1]).toEqual(["==", ["get", "gradient_percent"], null]);
  });

  it("勾配モードは符号付き（下り〜平坦〜上り）の5カテゴリ+データなし", () => {
    const gradient = getRouteStyleMode("gradient");
    expect(gradient.legend.map((entry) => entry.key)).toEqual([
      "downhill",
      "flat",
      "up-mild",
      "up-steep",
      "up-extreme",
      "nodata",
    ]);
    // 下りカテゴリの述語は「-2%未満」（進行方向基準の符号付き値をそのまま使う）
    const downhill = gradient.legend[0];
    expect(downhill.filter).toEqual([
      "all",
      ["!=", ["get", "gradient_percent"], null],
      ["<", ["to-number", ["get", "gradient_percent"]], -2],
    ]);
  });

  it("凡例タップのフィルタが風モードの各カテゴリで機能する（隣接カテゴリと境界が重ならない）", () => {
    const wind = getRouteStyleMode("wind");
    const normal = wind.legend.find((entry) => entry.key === "normal");
    expect(normal?.filter).toEqual([
      "all",
      ["!=", ["get", "wind_difficulty"], null],
      [">=", ["to-number", ["get", "wind_difficulty"]], 33],
      ["<", ["to-number", ["get", "wind_difficulty"]], 66],
    ]);
    expect(buildLegendFilterExpression(wind.legend, ["normal"])).toEqual(["all", ["!", normal!.filter]]);
  });

  it("isRouteStyleModeIdは既知のIDのみtrue（localStorageの壊れた値を弾く）", () => {
    expect(isRouteStyleModeId("wind")).toBe(true);
    expect(isRouteStyleModeId("gradient")).toBe(true);
    expect(isRouteStyleModeId("slope")).toBe(false);
    expect(isRouteStyleModeId("")).toBe(false);
    expect(isRouteStyleModeId(null)).toBe(false);
  });
});

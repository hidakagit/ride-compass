// @vitest-environment node
import { describe, expect, it } from "vitest";
import { buildLegendFilterExpression } from "./legendFilter";
import {
  DEFAULT_ROUTE_STYLE_MODE_ID,
  ROUTE_STYLE_MODES,
  getRouteStyleMode,
  isRouteStyleModeId,
} from "./routeStyleModes";

describe("routeStyleModes", () => {
  it("4つのモード（風の影響・勾配・路面・総合難易度）を定義し、デフォルトは風", () => {
    expect(ROUTE_STYLE_MODES.map((m) => m.id)).toEqual(["wind", "gradient", "road", "difficulty"]);
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
    const wind = getRouteStyleMode(ROUTE_STYLE_MODES, "wind");
    expect(wind.colorExpression[0]).toBe("case");
    expect(wind.colorExpression[1]).toEqual(["==", ["get", "wind", ["get", "axis_difficulties"]], null]);
    expect(wind.colorExpression[2]).toBe("#9ca3af");
    expect((wind.colorExpression[3] as unknown[])[0]).toBe("step");

    const gradient = getRouteStyleMode(ROUTE_STYLE_MODES, "gradient");
    expect(gradient.colorExpression[1]).toEqual(["==", ["get", "gradient_percent"], null]);
  });

  it("勾配モードは符号付き（下り〜平坦〜上り）の5カテゴリ+データなし", () => {
    const gradient = getRouteStyleMode(ROUTE_STYLE_MODES, "gradient");
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
    const wind = getRouteStyleMode(ROUTE_STYLE_MODES, "wind");
    const normal = wind.legend.find((entry) => entry.key === "normal");
    expect(normal?.filter).toEqual([
      "all",
      ["!=", ["get", "wind", ["get", "axis_difficulties"]], null],
      [">=", ["to-number", ["get", "wind", ["get", "axis_difficulties"]]], 33],
      ["<", ["to-number", ["get", "wind", ["get", "axis_difficulties"]]], 66],
    ]);
    expect(buildLegendFilterExpression(wind.legend, ["normal"])).toEqual(["all", ["!", normal!.filter]]);
  });

  it("路面モードは3値（舗装/未舗装/データなし）を判定値そのままで色分けする", () => {
    const road = getRouteStyleMode(ROUTE_STYLE_MODES, "road");
    expect(road.legend.map((entry) => entry.key)).toEqual(["paved", "unpaved", "nodata"]);
    // データ欠落（null）はグレーへ倒すのが最初の分岐（to-number変換を挟まない直接比較）
    expect(road.colorExpression[0]).toBe("case");
    expect(road.colorExpression[1]).toEqual(["==", ["get", "road_surface_good"], null]);
    expect(road.colorExpression[2]).toBe("#9ca3af");
    // 凡例タップのフィルタはtrue/false/nullの3値で排他になっている
    const paved = road.legend.find((entry) => entry.key === "paved");
    expect(paved?.filter).toEqual(["==", ["get", "road_surface_good"], true]);
    expect(buildLegendFilterExpression(road.legend, ["unpaved"])).toEqual([
      "all",
      ["!", ["==", ["get", "road_surface_good"], false]],
    ]);
  });

  it("総合難易度モードはdifficulty(0-100絶対基準)を風モードと同じ3段階で色分けする", () => {
    const difficulty = getRouteStyleMode(ROUTE_STYLE_MODES, "difficulty");
    expect(difficulty.legend.map((entry) => entry.key)).toEqual(["easy", "normal", "hard", "nodata"]);
    expect(difficulty.colorExpression[1]).toEqual(["==", ["get", "difficulty"], null]);
    const normal = difficulty.legend.find((entry) => entry.key === "normal");
    expect(normal?.filter).toEqual([
      "all",
      ["!=", ["get", "difficulty"], null],
      [">=", ["to-number", ["get", "difficulty"]], 33],
      ["<", ["to-number", ["get", "difficulty"]], 66],
    ]);
  });

  it("isRouteStyleModeIdは既知のIDのみtrue（localStorageの壊れた値を弾く）", () => {
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "wind")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "gradient")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "road")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "difficulty")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "slope")).toBe(false);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "")).toBe(false);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, null)).toBe(false);
  });
});

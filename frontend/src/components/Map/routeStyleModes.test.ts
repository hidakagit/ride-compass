// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import * as debugLogModule from "@/lib/debugLog";
import { buildLegendFilterExpression } from "./legendFilter";
import {
  DEFAULT_ROUTE_STYLE_MODE_ID,
  ROUTE_STYLE_MODES,
  filterRouteStyleModesByPreference,
  getRouteStyleMode,
  interpolateColors,
  isRouteStyleModeId,
  routeColorableModeFromAxis,
  routeStyleModesFromCatalogAxes,
} from "./routeStyleModes";
import type { CatalogAxis } from "./axisLayers";
import axisCatalog from "@/types/generated/axis-catalog.json";

const AXES = axisCatalog.axes as CatalogAxis[];
const gradientAxis = AXES.find((a) => a.axis_id === "gradient")!;
const windAxis = AXES.find((a) => a.axis_id === "wind")!;
const surfaceQAxis = AXES.find((a) => a.axis_id === "surface_q")!;

describe("routeStyleModes", () => {
  it("改善計画T440: gradient・wind・surface_q（動的）+ difficulty（固定）を定義し、デフォルトはROUTE_STYLE_MODES[0]と一致する", () => {
    expect(ROUTE_STYLE_MODES.map((m) => m.id)).toEqual(["gradient", "wind", "surface_q", "difficulty"]);
    expect(DEFAULT_ROUTE_STYLE_MODE_ID).toBe(ROUTE_STYLE_MODES[0].id);
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

  // 改善計画T466: id未検出時のmodes[0]無警告フォールバックへ警告ログを追加した回帰テスト。
  it("指定idが見つからない場合はmodes[0]へフォールバックしつつ警告を出す", () => {
    const debugLogSpy = vi.spyOn(debugLogModule, "debugLog").mockImplementation(() => {});

    const fallback = getRouteStyleMode(ROUTE_STYLE_MODES, "not-a-real-mode-id" as never);

    expect(fallback.id).toBe(ROUTE_STYLE_MODES[0].id);
    expect(debugLogSpy).toHaveBeenCalledWith(
      "map:route-style-mode",
      expect.stringContaining("not-a-real-mode-id"),
      expect.objectContaining({ requestedId: "not-a-real-mode-id" }),
      "warn"
    );

    debugLogSpy.mockRestore();
  });

  it("指定idが見つかった場合は警告を出さない", () => {
    const debugLogSpy = vi.spyOn(debugLogModule, "debugLog").mockImplementation(() => {});

    getRouteStyleMode(ROUTE_STYLE_MODES, "wind");

    expect(debugLogSpy).not.toHaveBeenCalled();
    debugLogSpy.mockRestore();
  });

  it("改善計画T440: gradient(shape.preprocess==='abs')はgradient_percentを符号付きのまま直接読む——軸idのハードコード分岐ではなくshapeの属性で判定する", () => {
    expect(gradientAxis.shape).toMatchObject({ kind: "breakpoint_linear", preprocess: "abs" });
    const mode = routeColorableModeFromAxis(gradientAxis);
    expect(mode.id).toBe("gradient");
    expect(mode.colorExpression[1]).toEqual(["==", ["get", "gradient_percent"], null]);
  });

  it("改善計画T440: gradientのしきい値は軸スタジオのdisplay_thresholds_override由来で、段階数はその長さ+1になる（固定5カテゴリを仮定しない）", () => {
    expect(gradientAxis.display_thresholds_override).toEqual([-2, 2, 6, 10]);
    const gradient = getRouteStyleMode(ROUTE_STYLE_MODES, "gradient");
    // データなし込みで4境界値+1段階+nodata = 6件
    expect(gradient.legend).toHaveLength(6);
    expect(gradient.legend.map((e) => e.label)).toEqual([
      "-2%未満",
      "-2〜2%",
      "2〜6%",
      "6〜10%",
      "10%超",
      "データなし",
    ]);
  });

  it("改善計画T440: 境界値が2個(3段階)しか無い場合でもクラッシュせず、その数に応じたラベル・色を生成する", () => {
    const axis: CatalogAxis = {
      ...gradientAxis,
      axis_id: "gradient_test",
      display_thresholds_override: [0, 5],
    };
    const mode = routeColorableModeFromAxis(axis);
    expect(mode.legend.map((e) => e.key)).toEqual(["step-0", "step-1", "step-2", "nodata"]);
    expect(mode.legend.map((e) => e.label)).toEqual(["0%未満", "0〜5%", "5%超", "データなし"]);
  });

  it("windはshape.preprocess!=='abs'のため通常の絶対値差難易度経路を使う（axis_difficulties経由）", () => {
    expect(windAxis.shape).toMatchObject({ kind: "breakpoint_linear", preprocess: "identity" });
    const wind = routeColorableModeFromAxis(windAxis);
    expect(wind.id).toBe("wind");
    expect(wind.label).toBe("風の影響");
    expect(wind.colorExpression[1]).toEqual(["==", ["get", "wind", ["get", "axis_difficulties"]], null]);
  });

  it("surface_q（shape.kind==='categorical'）も通常の絶対値差難易度経路を使い、ラベルは他の動的モードと同じ汎用形式になる（roadという専用名は無い）", () => {
    expect(surfaceQAxis.shape?.kind).toBe("categorical");
    const surfaceQ = routeColorableModeFromAxis(surfaceQAxis);
    expect(surfaceQ.id).toBe("surface_q");
    expect(surfaceQ.label).toBe(`${surfaceQAxis.label}の影響`);
    expect(surfaceQ.colorExpression[1]).toEqual(["==", ["get", "surface_q", ["get", "axis_difficulties"]], null]);
  });

  it("凡例タップのフィルタが風モードの各カテゴリで機能する（隣接カテゴリと境界が重ならない）", () => {
    const wind = getRouteStyleMode(ROUTE_STYLE_MODES, "wind");
    const middle = wind.legend[1];
    expect(middle.filter).toEqual([
      "all",
      ["!=", ["get", "wind", ["get", "axis_difficulties"]], null],
      [">=", ["to-number", ["get", "wind", ["get", "axis_difficulties"]]], 33],
      ["<", ["to-number", ["get", "wind", ["get", "axis_difficulties"]]], 66],
    ]);
    expect(buildLegendFilterExpression(wind.legend, [middle.key])).toEqual(["all", ["!", middle.filter]]);
  });

  it("総合難易度モードはdifficulty(0-100絶対基準)を色分けし、対応する軸を持たないため常に選択肢に残る", () => {
    const difficulty = getRouteStyleMode(ROUTE_STYLE_MODES, "difficulty");
    expect(difficulty.colorExpression[1]).toEqual(["==", ["get", "difficulty"], null]);
    const filtered = filterRouteStyleModesByPreference(ROUTE_STYLE_MODES, { gradient: 0, wind: 0, surface_q: 0 });
    expect(filtered.map((m) => m.id)).toEqual(["difficulty"]);
  });

  it("interpolateColorsは境界値の個数に関わらずcolorLow→colorHighの間をcount色生成する（固定色配列を持たない）", () => {
    expect(interpolateColors("#16a34a", "#dc2626", 1)).toEqual(["#16a34a"]);
    const three = interpolateColors("#16a34a", "#dc2626", 3);
    expect(three).toHaveLength(3);
    expect(three[0]).toBe("#16a34a");
    expect(three[2]).toBe("#dc2626");
    const five = interpolateColors("#0284c7", "#dc2626", 5);
    expect(five).toHaveLength(5);
    expect(new Set(five).size).toBe(5); // 全段階が異なる色になる
  });

  it("改善計画T440: filterRouteStyleModesByPreferenceは重み0の軸（gradient/wind/surface_q）を除外し、対応する軸を持たないdifficultyは常に残す", () => {
    const filtered = filterRouteStyleModesByPreference(ROUTE_STYLE_MODES, { gradient: 0, wind: 0.26, surface_q: 0.19 });
    expect(filtered.map((m) => m.id)).toEqual(["wind", "surface_q", "difficulty"]);
  });

  it("改善計画T440: gradient軸が軸カタログから消える（軸スタジオでunpublish）と、対応するモードも一覧から消える", () => {
    const axesWithoutGradient = AXES.filter((axis) => axis.axis_id !== "gradient");
    const modes = routeStyleModesFromCatalogAxes(axesWithoutGradient);
    expect(modes.map((m) => m.id)).toEqual(["wind", "surface_q", "difficulty"]);
  });

  it("改善計画T440: surface_q軸が軸カタログから消えると、対応するモードも一覧から消える", () => {
    const axesWithoutSurfaceQ = AXES.filter((axis) => axis.axis_id !== "surface_q");
    const modes = routeStyleModesFromCatalogAxes(axesWithoutSurfaceQ);
    expect(modes.map((m) => m.id)).toEqual(["gradient", "wind", "difficulty"]);
  });

  it("改善計画T440: difficultyはどの軸にも対応しないため、軸が0件でも一覧から消えない", () => {
    const modes = routeStyleModesFromCatalogAxes([]);
    expect(modes.map((m) => m.id)).toEqual(["difficulty"]);
  });

  it("isRouteStyleModeIdは既知のIDのみtrue（localStorageの壊れた値を弾く）", () => {
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "gradient")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "wind")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "surface_q")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "difficulty")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "road")).toBe(false);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "")).toBe(false);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, null)).toBe(false);
  });
});

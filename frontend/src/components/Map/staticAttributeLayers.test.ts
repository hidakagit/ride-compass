// @vitest-environment node
import { createExpression } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";
import type { LegendEntry } from "./legendFilter";
import { buildSafetyExpression, DEFAULT_SAFETY_RECIPE } from "./safetyExpression";
import {
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_CAR_STRESS_RECIPE,
  buildCarStressExpression,
} from "./carStressExpression";
import {
  ACCIDENT_COLOR_EXPRESSION,
  ACCIDENT_LEGEND,
  ACCIDENT_RADIUS_EXPRESSION,
  ACCIDENT_SEVERITY_LEGEND,
  BICYCLE_INFRA_COLOR_EXPRESSION,
  BICYCLE_INFRA_LEGEND,
  SAFETY_COLOR_EXPRESSION,
  SAFETY_LEGEND,
  STATIC_FILTER_AXES,
  STOP_POI_COLOR_EXPRESSION,
  STOP_POI_KINDS,
  STOP_POI_LABELS,
  STOP_POI_LEGEND,
  SUPPLY_POI_COLOR_EXPRESSION,
  SUPPLY_POI_KINDS,
  SUPPLY_POI_LABELS,
  SUPPLY_POI_LEGEND,
  CAR_STRESS_COLOR_EXPRESSION,
  CAR_STRESS_LEGEND,
  buildSafetyColorExpression,
  buildSafetyLegend,
  buildCarStressColorExpression,
  buildCarStressLegend,
} from "./staticAttributeLayers";

// MapLibre expressionを実評価するヘルパー（carStressExpression.test.tsと同じ手法）。
function evaluateFilter(filter: unknown, properties: Record<string, unknown>): boolean {
  const parsed = createExpression(filter);
  if (parsed.result !== "success") throw new Error("filter式の構築に失敗しました");
  return Boolean(parsed.value.evaluate({ zoom: 14 }, { type: "Unknown", properties }));
}

describe("staticAttributeLayers", () => {
  it("車ストレスの凡例キーは1-5+不明で、重複が無い", () => {
    const keys = CAR_STRESS_LEGEND.map((e) => e.key);
    expect(new Set(keys)).toEqual(new Set(["1", "2", "3", "4", "5", "unknown"]));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("車ストレスのmatch式はプロパティ欠落時に凡例のunknown色へ落ちる", () => {
    expect(CAR_STRESS_COLOR_EXPRESSION[0]).toBe("match");
    const unknownColor = CAR_STRESS_LEGEND.find((e) => e.key === "unknown")!.color;
    expect(CAR_STRESS_COLOR_EXPRESSION[CAR_STRESS_COLOR_EXPRESSION.length - 1]).toBe(unknownColor);
  });

  it("凡例の色とmatch式に出てくる色が一致する（凡例に無い色で描画されない）", () => {
    const legendColors = new Set(CAR_STRESS_LEGEND.map((e) => e.color));
    const expressionColors = CAR_STRESS_COLOR_EXPRESSION.filter(
      (item): item is string => typeof item === "string" && item.startsWith("#"),
    );
    for (const color of expressionColors) {
      expect(legendColors.has(color)).toBe(true);
    }
  });

  // 改善計画: 車ストレスレシピ調整UIパネル。buildCarStressLegend/
  // buildCarStressColorExpressionはレシピを引数に取る関数化されており、
  // CAR_STRESS_LEGEND/CAR_STRESS_COLOR_EXPRESSIONはその既定レシピ版（無変更）。
  describe("buildCarStressLegend/buildCarStressColorExpression（レシピ引数）", () => {
    it("既定レシピを渡すと既存のCAR_STRESS_LEGEND/COLOR_EXPRESSIONと同じ内容になる", () => {
      expect(buildCarStressLegend(DEFAULT_CAR_STRESS_RECIPE)).toEqual(CAR_STRESS_LEGEND);
      expect(buildCarStressColorExpression(DEFAULT_CAR_STRESS_RECIPE)).toEqual(CAR_STRESS_COLOR_EXPRESSION);
    });

    it("道路適正レシピのbase_by_highwayを変えると、そのhighwayのフィーチャーが属するカテゴリが変わる", () => {
      // base_by_highwayは道路適正レシピ側（改善計画: 車との近さ材料の共有元化）。
      // levelExpressionを明示的に組み立てて渡す（buildCarStressLegendのdocstring参照）。
      const customRoadSuitabilityRecipe = {
        ...DEFAULT_ROAD_SUITABILITY_RECIPE,
        base_by_highway: { ...DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway, secondary: 1 },
      };
      const legend = buildCarStressLegend(
        DEFAULT_CAR_STRESS_RECIPE,
        buildCarStressExpression(DEFAULT_CAR_STRESS_RECIPE, customRoadSuitabilityRecipe),
      );
      const properties = { highway: "secondary" };

      // 既定レシピ（secondary=3）では"3"カテゴリに属するが、customRecipe（secondary=1）では
      // "1"カテゴリに属する。
      const defaultLegend = buildCarStressLegend(DEFAULT_CAR_STRESS_RECIPE);
      expect(evaluateFilter(defaultLegend.find((e) => e.key === "3")!.filter, properties)).toBe(true);
      expect(evaluateFilter(legend.find((e) => e.key === "1")!.filter, properties)).toBe(true);
      expect(evaluateFilter(legend.find((e) => e.key === "3")!.filter, properties)).toBe(false);
    });

    it("凡例のラベル・色・key構成自体はレシピに関わらず不変（変わるのはfilterの中身だけ）", () => {
      const customRecipe = { ...DEFAULT_CAR_STRESS_RECIPE, lanes_low_adjustment: -3 };
      const legend = buildCarStressLegend(customRecipe);
      expect(legend.map((e) => ({ key: e.key, label: e.label, color: e.color, isFallback: e.isFallback }))).toEqual(
        CAR_STRESS_LEGEND.map((e) => ({ key: e.key, label: e.label, color: e.color, isFallback: e.isFallback })),
      );
    });
  });

  it("安全度の凡例キーは1-4+不明で、重複が無い", () => {
    const keys = SAFETY_LEGEND.map((e) => e.key);
    expect(new Set(keys)).toEqual(new Set(["1", "2", "3", "4", "unknown"]));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("安全度のmatch式はプロパティ欠落時に凡例のunknown色へ落ちる", () => {
    expect(SAFETY_COLOR_EXPRESSION[0]).toBe("match");
    const unknownColor = SAFETY_LEGEND.find((e) => e.key === "unknown")!.color;
    expect(SAFETY_COLOR_EXPRESSION[SAFETY_COLOR_EXPRESSION.length - 1]).toBe(unknownColor);
  });

  it("安全度の凡例の色は車ストレスの凡例の色と重ならない（地図上で混同しない、不明・他の共通灰色を除く）", () => {
    const carStressColors = new Set(
      CAR_STRESS_LEGEND.filter((e) => e.key !== "unknown").map((e) => e.color),
    );
    const safetyColors = SAFETY_LEGEND.filter((e) => e.key !== "unknown").map((e) => e.color);
    for (const color of safetyColors) {
      expect(carStressColors.has(color)).toBe(false);
    }
  });

  // 改善計画: 安全度レシピ。buildCarStressLegend/buildCarStressColorExpressionと
  // 同じ構造（レシピを引数に取る関数化）。
  describe("buildSafetyLegend/buildSafetyColorExpression（レシピ引数）", () => {
    it("既定レシピを渡すと既存のSAFETY_LEGEND/COLOR_EXPRESSIONと同じ内容になる", () => {
      expect(buildSafetyLegend(DEFAULT_SAFETY_RECIPE)).toEqual(SAFETY_LEGEND);
      expect(buildSafetyColorExpression(DEFAULT_SAFETY_RECIPE)).toEqual(SAFETY_COLOR_EXPRESSION);
    });

    it("道路適正レシピのbase_by_highwayを変えると、そのhighwayのフィーチャーが属するカテゴリが変わる", () => {
      // base_by_highwayは道路適正レシピ側（改善計画: 車との近さ材料の共有元化）。
      const customRoadSuitabilityRecipe = {
        ...DEFAULT_ROAD_SUITABILITY_RECIPE,
        base_by_highway: { ...DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway, secondary: 1 },
      };
      const legend = buildSafetyLegend(
        DEFAULT_SAFETY_RECIPE,
        buildSafetyExpression(DEFAULT_SAFETY_RECIPE, customRoadSuitabilityRecipe),
      );
      const properties = { highway: "secondary" };

      const defaultLegend = buildSafetyLegend(DEFAULT_SAFETY_RECIPE);
      expect(evaluateFilter(defaultLegend.find((e) => e.key === "3")!.filter, properties)).toBe(true);
      expect(evaluateFilter(legend.find((e) => e.key === "1")!.filter, properties)).toBe(true);
      expect(evaluateFilter(legend.find((e) => e.key === "3")!.filter, properties)).toBe(false);
    });

    it("凡例のラベル・色・key構成自体はレシピに関わらず不変（変わるのはfilterの中身だけ）", () => {
      const customRecipe = { ...DEFAULT_SAFETY_RECIPE, lit_adjustment: -3 };
      const legend = buildSafetyLegend(customRecipe);
      expect(legend.map((e) => ({ key: e.key, label: e.label, color: e.color, isFallback: e.isFallback }))).toEqual(
        SAFETY_LEGEND.map((e) => ({ key: e.key, label: e.label, color: e.color, isFallback: e.isFallback })),
      );
    });
  });

  it("自転車インフラの凡例キーはdomain/traffic.pyのBicycleInfraClass列挙値+不明と一致する", () => {
    const keys = BICYCLE_INFRA_LEGEND.map((e) => e.key);
    expect(new Set(keys)).toEqual(
      new Set(["separated", "lane", "shared_busway", "shared_pedestrian", "roadway", "prohibited", "unknown"]),
    );
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("自転車インフラのmatch式はプロパティ欠落時に凡例のunknown色へ落ちる", () => {
    expect(BICYCLE_INFRA_COLOR_EXPRESSION[0]).toBe("match");
    const unknownColor = BICYCLE_INFRA_LEGEND.find((e) => e.key === "unknown")!.color;
    expect(BICYCLE_INFRA_COLOR_EXPRESSION[BICYCLE_INFRA_COLOR_EXPRESSION.length - 1]).toBe(unknownColor);
  });

  it("自転車インフラの凡例の色とmatch式に出てくる色が一致する", () => {
    const legendColors = new Set(BICYCLE_INFRA_LEGEND.map((e) => e.color));
    const expressionColors = BICYCLE_INFRA_COLOR_EXPRESSION.filter(
      (item): item is string => typeof item === "string" && item.startsWith("#"),
    );
    for (const color of expressionColors) {
      expect(legendColors.has(color)).toBe(true);
    }
  });

  it("各軸とも凡例エントリごとに一意な色を持つ（見分けられる配色）", () => {
    for (const legend of [CAR_STRESS_LEGEND, SAFETY_LEGEND, BICYCLE_INFRA_LEGEND]) {
      const colors = legend.map((e) => e.color);
      expect(new Set(colors).size).toBe(colors.length);
    }
  });

  it("事故レイヤーの凡例キーは自転車関連/その他の2値で重複が無い", () => {
    const keys = ACCIDENT_LEGEND.map((e) => e.key);
    expect(new Set(keys)).toEqual(new Set(["bicycle", "other"]));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("事故レイヤーの凡例は一意な色を持つ", () => {
    const colors = ACCIDENT_LEGEND.map((e) => e.color);
    expect(new Set(colors).size).toBe(colors.length);
  });

  it("事故レイヤーの色分け式は凡例の色以外を使わない", () => {
    const legendColors = new Set(ACCIDENT_LEGEND.map((e) => e.color));
    const expressionColors = ACCIDENT_COLOR_EXPRESSION.filter(
      (item): item is string => typeof item === "string" && item.startsWith("#"),
    );
    expect(expressionColors.length).toBeGreaterThan(0);
    for (const color of expressionColors) {
      expect(legendColors.has(color)).toBe(true);
    }
  });

  it("死亡事故（fatal=true）は非死亡事故より大きい円で強調される", () => {
    expect(ACCIDENT_RADIUS_EXPRESSION[0]).toBe("case");
    const [, , fatalRadius, defaultRadius] = ACCIDENT_RADIUS_EXPRESSION as [string, unknown[], number, number];
    expect(fatalRadius).toBeGreaterThan(defaultRadius);
  });

  // 改善計画T54: 停止要因POI・交差点密度。
  it("停止要因POIの凡例キーはbackend/app/domain/traffic.pyのStopPoiKind5値+不明と一致する", () => {
    const keys = STOP_POI_LEGEND.map((e) => e.key);
    expect(new Set(keys)).toEqual(
      new Set(["traffic_signals", "crossing", "stop", "give_way", "level_crossing", "unknown"]),
    );
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("停止要因POIの凡例エントリごとに一意な色を持つ", () => {
    const colors = STOP_POI_LEGEND.map((e) => e.color);
    expect(new Set(colors).size).toBe(colors.length);
  });

  it("停止要因POIの凡例の色とmatch式に出てくる色が一致する", () => {
    const legendColors = new Set(STOP_POI_LEGEND.map((e) => e.color));
    const expressionColors = STOP_POI_COLOR_EXPRESSION.filter(
      (item): item is string => typeof item === "string" && item.startsWith("#"),
    );
    for (const color of expressionColors) {
      expect(legendColors.has(color)).toBe(true);
    }
  });

  it("STOP_POI_LABELSは凡例のkey→labelと一致する（ポップアップ表示用の対訳表。unknownは対訳表に無く呼び出し側でフォールバックする）", () => {
    for (const entry of STOP_POI_LEGEND.filter((e) => e.key !== "unknown")) {
      expect(STOP_POI_LABELS[entry.key]).toBe(entry.label);
    }
  });

  // 改善計画T101: 補給・休憩ポイントPOI。停止要因POIと同じベクタタイル（kindプロパティ）を
  // 共有するため、STOP_POI_KINDS/SUPPLY_POI_KINDSが重複しないことも合わせて検証する
  // （重複するとbaseFilterによる2レイヤー分離が壊れ、両方に同じ地物が出てしまう）。
  it("補給・休憩ポイントの凡例キーはbackend/app/domain/traffic.pyのSupplyPoiKind5値+不明と一致する", () => {
    const keys = SUPPLY_POI_LEGEND.map((e) => e.key);
    expect(new Set(keys)).toEqual(
      new Set(["convenience", "vending_machine", "toilets", "drinking_water", "bicycle_parking", "unknown"]),
    );
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("補給・休憩ポイントの凡例エントリごとに一意な色を持つ", () => {
    const colors = SUPPLY_POI_LEGEND.map((e) => e.color);
    expect(new Set(colors).size).toBe(colors.length);
  });

  it("補給・休憩ポイントの凡例の色とmatch式に出てくる色が一致する", () => {
    const legendColors = new Set(SUPPLY_POI_LEGEND.map((e) => e.color));
    const expressionColors = SUPPLY_POI_COLOR_EXPRESSION.filter(
      (item): item is string => typeof item === "string" && item.startsWith("#"),
    );
    for (const color of expressionColors) {
      expect(legendColors.has(color)).toBe(true);
    }
  });

  it("SUPPLY_POI_LABELSは凡例のkey→labelと一致する", () => {
    for (const entry of SUPPLY_POI_LEGEND.filter((e) => e.key !== "unknown")) {
      expect(SUPPLY_POI_LABELS[entry.key]).toBe(entry.label);
    }
  });

  it("STOP_POI_KINDSとSUPPLY_POI_KINDSは重複しない（同じベクタタイルを共有する2レイヤーのbaseFilter分離の前提）", () => {
    const overlap = STOP_POI_KINDS.filter((k) => (SUPPLY_POI_KINDS as readonly string[]).includes(k));
    expect(overlap).toEqual([]);
  });

  // 改善計画T63: 事故の「重大度」絞り込み軸（当事者=ACCIDENT_LEGENDとは独立、AND絞り込み）。
  it("事故の重大度の凡例キーは死亡事故/死亡事故以外の2値で重複が無い", () => {
    const keys = ACCIDENT_SEVERITY_LEGEND.map((e) => e.key);
    expect(new Set(keys)).toEqual(new Set(["fatal", "nonfatal"]));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("事故の重大度の凡例は一意な色を持つ", () => {
    const colors = ACCIDENT_SEVERITY_LEGEND.map((e) => e.color);
    expect(new Set(colors).size).toBe(colors.length);
  });

  // 改善計画T63: 絞り込みUIカタログ（STATIC_FILTER_AXES）自体の整合性。
  it("STATIC_FILTER_AXESの軸idに重複が無い", () => {
    const axisIds = STATIC_FILTER_AXES.map((axis) => axis.axisId);
    expect(new Set(axisIds).size).toBe(axisIds.length);
  });

  it("STATIC_FILTER_AXESの各軸は対応するLEGEND定数と同じ内容を参照する", () => {
    const byAxisId = Object.fromEntries(STATIC_FILTER_AXES.map((axis) => [axis.axisId, axis.legend]));
    const expected: Record<string, readonly LegendEntry[]> = {
      carStress: CAR_STRESS_LEGEND,
      safety: SAFETY_LEGEND,
      bicycleInfra: BICYCLE_INFRA_LEGEND,
      stopPoi: STOP_POI_LEGEND,
      supplyPoi: SUPPLY_POI_LEGEND,
      accidentParty: ACCIDENT_LEGEND,
      accidentSeverity: ACCIDENT_SEVERITY_LEGEND,
    };
    for (const [axisId, legend] of Object.entries(expected)) {
      expect(byAxisId[axisId]).toBe(legend);
    }
  });

  it("stopPoi/supplyPoi軸はそれぞれ自分のkind値集合へ絞るbaseFilterを持つ（改善計画T101）", () => {
    const stopPoiAxis = STATIC_FILTER_AXES.find((axis) => axis.axisId === "stopPoi");
    const supplyPoiAxis = STATIC_FILTER_AXES.find((axis) => axis.axisId === "supplyPoi");
    expect(stopPoiAxis?.baseFilter).toEqual(["in", ["get", "kind"], ["literal", STOP_POI_KINDS]]);
    expect(supplyPoiAxis?.baseFilter).toEqual(["in", ["get", "kind"], ["literal", SUPPLY_POI_KINDS]]);
    // 他の軸（例: carStress）はkindプロパティを持たない別ソースのためbaseFilter不要。
    expect(STATIC_FILTER_AXES.find((axis) => axis.axisId === "carStress")?.baseFilter).toBeUndefined();
  });

  it("事故は当事者・重大度の2軸を持ち、それ以外のレイヤーは1軸のみ", () => {
    const countsByLayer = new Map<string, number>();
    for (const axis of STATIC_FILTER_AXES) {
      countsByLayer.set(axis.layerId, (countsByLayer.get(axis.layerId) ?? 0) + 1);
    }
    expect(countsByLayer.get("accidents")).toBe(2);
    for (const [layerId, count] of countsByLayer) {
      if (layerId !== "accidents") expect(count).toBe(1);
    }
  });
});

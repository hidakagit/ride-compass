import { describe, expect, it } from "vitest";
import type { LegendEntry } from "./legendFilter";
import {
  ACCIDENT_COLOR_EXPRESSION,
  ACCIDENT_LEGEND,
  ACCIDENT_RADIUS_EXPRESSION,
  ACCIDENT_SEVERITY_LEGEND,
  BICYCLE_INFRA_COLOR_EXPRESSION,
  BICYCLE_INFRA_LEGEND,
  STATIC_FILTER_AXES,
  STOP_POI_COLOR_EXPRESSION,
  STOP_POI_LABELS,
  STOP_POI_LEGEND,
  TRAFFIC_STRESS_COLOR_EXPRESSION,
  TRAFFIC_STRESS_LEGEND,
} from "./staticAttributeLayers";

describe("staticAttributeLayers", () => {
  it("交通ストレスの凡例キーは1-4+不明で、重複が無い", () => {
    const keys = TRAFFIC_STRESS_LEGEND.map((e) => e.key);
    expect(new Set(keys)).toEqual(new Set(["1", "2", "3", "4", "unknown"]));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("交通ストレスのmatch式はプロパティ欠落時に凡例のunknown色へ落ちる", () => {
    expect(TRAFFIC_STRESS_COLOR_EXPRESSION[0]).toBe("match");
    const unknownColor = TRAFFIC_STRESS_LEGEND.find((e) => e.key === "unknown")!.color;
    expect(TRAFFIC_STRESS_COLOR_EXPRESSION[TRAFFIC_STRESS_COLOR_EXPRESSION.length - 1]).toBe(unknownColor);
  });

  it("凡例の色とmatch式に出てくる色が一致する（凡例に無い色で描画されない）", () => {
    const legendColors = new Set(TRAFFIC_STRESS_LEGEND.map((e) => e.color));
    const expressionColors = TRAFFIC_STRESS_COLOR_EXPRESSION.filter(
      (item): item is string => typeof item === "string" && item.startsWith("#"),
    );
    for (const color of expressionColors) {
      expect(legendColors.has(color)).toBe(true);
    }
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

  it("両軸とも凡例エントリごとに一意な色を持つ（見分けられる配色）", () => {
    for (const legend of [TRAFFIC_STRESS_LEGEND, BICYCLE_INFRA_LEGEND]) {
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
      trafficStress: TRAFFIC_STRESS_LEGEND,
      bicycleInfra: BICYCLE_INFRA_LEGEND,
      stopPoi: STOP_POI_LEGEND,
      accidentParty: ACCIDENT_LEGEND,
      accidentSeverity: ACCIDENT_SEVERITY_LEGEND,
    };
    for (const [axisId, legend] of Object.entries(expected)) {
      expect(byAxisId[axisId]).toBe(legend);
    }
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

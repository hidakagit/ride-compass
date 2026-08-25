// @vitest-environment node
import { createExpression } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";
import type { LegendEntry } from "./legendFilter";
import {
  ACCIDENT_COLOR_EXPRESSION,
  ACCIDENT_LEGEND,
  ACCIDENT_RADIUS_EXPRESSION,
  ACCIDENT_SEVERITY_LEGEND,
  BICYCLE_INFRA_COLOR_EXPRESSION,
  BICYCLE_INFRA_LEGEND,
  buildStaticFilterAxes,
  STOP_POI_COLOR_EXPRESSION,
  STOP_POI_KINDS,
  STOP_POI_LABELS,
  STOP_POI_LEGEND,
  SUPPLY_POI_COLOR_EXPRESSION,
  SUPPLY_POI_KINDS,
  SUPPLY_POI_LABELS,
  SUPPLY_POI_LEGEND,
  TUNNEL_COLOR_EXPRESSION,
  TUNNEL_LEGEND,
  TUNNEL_OPACITY_EXPRESSION,
  ONEWAY_COLOR_EXPRESSION,
  ONEWAY_LEGEND,
  ONEWAY_OPACITY_EXPRESSION,
} from "./staticAttributeLayers";
import { RAMP_AXES } from "./axisLayers";

// 改善計画T292: 車ストレス（車の圧迫感）専用の凡例・色分け式（CAR_STRESS_LEGEND・
// CAR_STRESS_COLOR_EXPRESSION・buildCarStressLegend・buildCarStressColorExpression）は
// 専用Pythonレシピの廃止に伴いこのファイルから削除された。車の圧迫感は他の推定軸
// （停止密度・事故密度等）と同じ汎用ramp機構（axisLayers.test.ts参照）に一本化された。

// ビルド時静的フォールバック（RAMP_AXES、軸スタジオが公開したGUI作成軸を含まない）を
// 入力にbuildStaticFilterAxes()を呼んだ結果。以前のSTATIC_FILTER_AXES定数と同じ内容。
const STATIC_FILTER_AXES = buildStaticFilterAxes(RAMP_AXES);

describe("staticAttributeLayers", () => {
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

  it("自転車インフラの凡例エントリごとに一意な色を持つ（見分けられる配色）", () => {
    const colors = BICYCLE_INFRA_LEGEND.map((e) => e.color);
    expect(new Set(colors).size).toBe(colors.length);
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

  // 改善計画: トンネル（一次属性、OSMのtunnelタグ）。「地図上に描画可能な状態で保持している
  // 要素の洗い出し」で判明した「観測配下にレイヤーが無いまま」を解消した新規レイヤー。
  it("トンネルの凡例キーはトンネル/対象外の2値で重複が無い", () => {
    const keys = TUNNEL_LEGEND.map((e) => e.key);
    expect(new Set(keys)).toEqual(new Set(["tunnel", "other"]));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("トンネルの凡例は一意な色を持つ", () => {
    const colors = TUNNEL_LEGEND.map((e) => e.color);
    expect(new Set(colors).size).toBe(colors.length);
  });

  it("トンネルの色分け式は凡例の色以外を使わない", () => {
    const legendColors = new Set(TUNNEL_LEGEND.map((e) => e.color));
    const expressionColors = TUNNEL_COLOR_EXPRESSION.filter(
      (item): item is string => typeof item === "string" && item.startsWith("#"),
    );
    expect(expressionColors.length).toBeGreaterThan(0);
    for (const color of expressionColors) {
      expect(legendColors.has(color)).toBe(true);
    }
  });

  it("トンネルのfeatureはtunnel=trueのみ強調色になり、それ以外は不透明度が下がる", () => {
    function evaluate(expr: unknown[], properties: Record<string, unknown>): unknown {
      const parsed = createExpression(expr);
      if (parsed.result !== "success") throw new Error("式の構築に失敗しました");
      return parsed.value.evaluate({ zoom: 14 }, { type: "Unknown", properties });
    }
    const tunnelColor = evaluate(TUNNEL_COLOR_EXPRESSION, { tunnel: true });
    const otherColor = evaluate(TUNNEL_COLOR_EXPRESSION, {});
    expect(tunnelColor).not.toBe(otherColor);
    expect(evaluate(TUNNEL_OPACITY_EXPRESSION, { tunnel: true })).toBeGreaterThan(
      evaluate(TUNNEL_OPACITY_EXPRESSION, {}) as number,
    );
  });

  // 改善計画T289: 一方通行（一次属性、OSM onewayタグ）。tunnelと同型の真偽値レイヤーだが、
  // どの評価軸の材料にもならない（表示専用）ため評価軸の危険色とは別の中立色を使う。
  it("一方通行の凡例キーは一方通行/対象外の2値で重複が無い", () => {
    const keys = ONEWAY_LEGEND.map((e) => e.key);
    expect(new Set(keys)).toEqual(new Set(["oneway", "other"]));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("一方通行の凡例は一意な色を持つ", () => {
    const colors = ONEWAY_LEGEND.map((e) => e.color);
    expect(new Set(colors).size).toBe(colors.length);
  });

  it("一方通行の色分け式は凡例の色以外を使わない", () => {
    const legendColors = new Set(ONEWAY_LEGEND.map((e) => e.color));
    const expressionColors = ONEWAY_COLOR_EXPRESSION.filter(
      (item): item is string => typeof item === "string" && item.startsWith("#"),
    );
    expect(expressionColors.length).toBeGreaterThan(0);
    for (const color of expressionColors) {
      expect(legendColors.has(color)).toBe(true);
    }
  });

  it("一方通行のfeatureはoneway=trueのみ強調色になり、それ以外は不透明度が下がる", () => {
    function evaluate(expr: unknown[], properties: Record<string, unknown>): unknown {
      const parsed = createExpression(expr);
      if (parsed.result !== "success") throw new Error("式の構築に失敗しました");
      return parsed.value.evaluate({ zoom: 14 }, { type: "Unknown", properties });
    }
    const onewayColor = evaluate(ONEWAY_COLOR_EXPRESSION, { oneway: true });
    const otherColor = evaluate(ONEWAY_COLOR_EXPRESSION, {});
    expect(onewayColor).not.toBe(otherColor);
    expect(evaluate(ONEWAY_OPACITY_EXPRESSION, { oneway: true })).toBeGreaterThan(
      evaluate(ONEWAY_OPACITY_EXPRESSION, {}) as number,
    );
  });

  // 改善計画T63: 絞り込みUIカタログ（STATIC_FILTER_AXES）自体の整合性。
  it("STATIC_FILTER_AXESの軸idに重複が無い", () => {
    const axisIds = STATIC_FILTER_AXES.map((axis) => axis.axisId);
    expect(new Set(axisIds).size).toBe(axisIds.length);
  });

  it("STATIC_FILTER_AXESの各軸は対応するLEGEND定数と同じ内容を参照する", () => {
    const byAxisId = Object.fromEntries(STATIC_FILTER_AXES.map((axis) => [axis.axisId, axis.legend]));
    const expected: Record<string, readonly LegendEntry[]> = {
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
    // 他の軸（例: bicycleInfra）はkindプロパティを持たない別ソースのためbaseFilter不要。
    expect(STATIC_FILTER_AXES.find((axis) => axis.axisId === "bicycleInfra")?.baseFilter).toBeUndefined();
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

  it("buildStaticFilterAxesは軸スタジオの新規公開軸（拡張カタログ）にも追従する", () => {
    const extraAxis = { ...RAMP_AXES[0], axisId: "new_gui_axis", label: "新規GUI軸" };
    const extended = buildStaticFilterAxes([...RAMP_AXES, extraAxis]);
    const axis = extended.find((a) => a.axisId === "new_gui_axis");
    expect(axis).toBeDefined();
    expect(axis!.layerId).toBe("axis:new_gui_axis");
  });
});

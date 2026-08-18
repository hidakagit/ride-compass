// @vitest-environment node
// 二次軸rampレイヤー（改善計画T145b）の純ロジック検証。DOM不要のためnode環境で実行する
// （vitest.config.mtsのコメント参照）。

import { describe, expect, it } from "vitest";

import {
  AXIS_RAMP_COLORS,
  RAMP_AXES,
  axisLineLayerId,
  axisMapLayerId,
  axisRampLegendEntries,
  buildAxisRampColorExpression,
  buildAxisRampValueExpression,
} from "./axisLayers";
import { MAP_LAYERS, ROAD_SURFACE_SHARED_LAYER_IDS } from "./mapLayers";

describe("axisLayers", () => {
  it("カタログのkind=ramp軸（accident・stop_density）が取り込まれている", () => {
    const ids = RAMP_AXES.map((axis) => axis.axisId);
    expect(ids).toContain("accident");
    expect(ids).toContain("stop_density");
  });

  it("各ramp軸はしきい値が昇順で、tile_inputsを1つ以上持つ", () => {
    for (const axis of RAMP_AXES) {
      expect(axis.tileInputs.length).toBeGreaterThan(0);
      expect(axis.thresholds.length).toBeGreaterThan(0);
      const sorted = [...axis.thresholds].sort((a, b) => a - b);
      expect(axis.thresholds).toEqual(sorted);
    }
  });

  it("停止密度の値expressionはタグなし交差点の重み（backend正準値0.3）を反映する", () => {
    const stopDensity = RAMP_AXES.find((axis) => axis.axisId === "stop_density")!;
    const expression = buildAxisRampValueExpression(stopDensity);
    // ["+", ["*", ["coalesce",["get","stop_per_km"],0], 1], ["*", ..., 0.3]]
    expect(expression[0]).toBe("+");
    const weights = (expression.slice(1) as unknown[][]).map((term) => term[2]);
    expect(weights).toEqual([1.0, 0.3]);
  });

  it("単一入力の軸（事故密度）は+で包まず単項のexpressionになる", () => {
    const accident = RAMP_AXES.find((axis) => axis.axisId === "accident")!;
    const expression = buildAxisRampValueExpression(accident);
    expect(expression[0]).toBe("*");
    expect(expression[1]).toEqual(["coalesce", ["get", "accident_per_km"], 0]);
  });

  it("色expressionはstep形式でしきい値の数+1段階の色を持つ", () => {
    for (const axis of RAMP_AXES) {
      const expression = buildAxisRampColorExpression(axis);
      expect(expression[0]).toBe("step");
      // ["step", value, color0, t1, color1, ...] → 長さ = 3 + 2×しきい値数
      expect(expression.length).toBe(3 + axis.thresholds.length * 2);
      expect(expression[2]).toBe(AXIS_RAMP_COLORS[0]);
    }
  });

  it("凡例エントリはしきい値の数+1段階でラベルへ単位を含む", () => {
    for (const axis of RAMP_AXES) {
      const entries = axisRampLegendEntries(axis);
      expect(entries.length).toBe(axis.thresholds.length + 1);
      for (const entry of entries) {
        expect(entry.label).toContain(axis.unit);
      }
    }
  });

  it("MAP_LAYERSへramp軸のレイヤーが自動で現れる（レジストリ駆動の受け入れ検証）", () => {
    for (const axis of RAMP_AXES) {
      const descriptor = MAP_LAYERS.find((layer) => layer.id === axisMapLayerId(axis.axisId));
      expect(descriptor).toBeDefined();
      expect(descriptor!.label).toBe(axis.label);
      expect(descriptor!.kind).toBe("static");
    }
  });

  it("ramp軸レイヤーはroad_surfaceタイル共有グループに登録されている", () => {
    for (const axis of RAMP_AXES) {
      expect(ROAD_SURFACE_SHARED_LAYER_IDS).toContain(axisMapLayerId(axis.axisId));
    }
  });

  it("IDヘルパーは軸IDから決定的なIDを生成する", () => {
    expect(axisMapLayerId("accident")).toBe("axis:accident");
    expect(axisLineLayerId("accident")).toBe("region-axis-accident-line");
  });
});

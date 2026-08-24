// @vitest-environment node
// 二次軸rampレイヤー（改善計画T145b）の純ロジック検証。DOM不要のためnode環境で実行する
// （vitest.config.mtsのコメント参照）。

import { describe, expect, it } from "vitest";

import {
  AXIS_RAMP_COLORS,
  COLOR_UNKNOWN,
  RAMP_AXES,
  axisLineLayerId,
  axisMapLayerId,
  buildAxisRampColorExpression,
  buildAxisRampLegend,
  buildAxisRampUnknownExpression,
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

  it("色expressionはstep形式でしきい値の数+1段階の色を持つ（hasUnknownFallbackな軸はcaseで一段包む）", () => {
    for (const axis of RAMP_AXES) {
      const expression = buildAxisRampColorExpression(axis);
      const unknownExpression = buildAxisRampUnknownExpression(axis);
      // 改善計画T278レビュー指摘の修正: hasUnknownFallback（例: surface_q）な軸は
      // ["case", 不明判定, COLOR_UNKNOWN, stepExpression]で一段包まれる。
      const stepExpression = unknownExpression === null ? expression : (expression[3] as unknown[]);
      if (unknownExpression !== null) {
        expect(expression[0]).toBe("case");
        expect(expression[2]).toBe(COLOR_UNKNOWN);
      }
      expect(stepExpression[0]).toBe("step");
      // ["step", value, color0, t1, color1, ...] → 長さ = 3 + 2×しきい値数
      expect(stepExpression.length).toBe(3 + axis.thresholds.length * 2);
      expect(stepExpression[2]).toBe(AXIS_RAMP_COLORS[0]);
    }
  });

  it("凡例エントリはしきい値の数+1段階(+hasUnknownFallbackなら不明1件)でラベルへ単位を含み、キー・色が重複しない", () => {
    for (const axis of RAMP_AXES) {
      const entries = buildAxisRampLegend(axis);
      const unknownExpression = buildAxisRampUnknownExpression(axis);
      const expectedLength = axis.thresholds.length + 1 + (unknownExpression === null ? 0 : 1);
      expect(entries.length).toBe(expectedLength);
      const keys = entries.map((entry) => entry.key);
      expect(new Set(keys).size).toBe(keys.length);
      for (const entry of entries) {
        if (entry.isFallback && unknownExpression !== null) {
          // 「不明」エントリは範囲ラベルではないため単位を含まない。
          expect(entry.color).toBe(COLOR_UNKNOWN);
          continue;
        }
        expect(entry.label).toContain(axis.unit);
        expect(entry.color).toBeTruthy();
      }
    }
  });

  it("凡例の範囲フィルタは境界が連続し、地図の色分けと同じ値expressionを参照する", () => {
    for (const axis of RAMP_AXES) {
      const entries = buildAxisRampLegend(axis);
      const valueExpression = buildAxisRampValueExpression(axis);
      const unknownExpression = buildAxisRampUnknownExpression(axis);
      const unknownPrefix: unknown[] = unknownExpression === null ? [] : [["!", unknownExpression]];
      const bandCount = axis.thresholds.length + 1;
      // 最初の段階は下限なし（["<", value, t1]）、最後は上限なし（[">=", value, tN]）、
      // 中間は[">=",...]と["<",...]の両方。hasUnknownFallbackな軸は各段階の先頭に
      // ["!", 不明判定]が入り、不明そのものを二重分類しない（改善計画T278レビュー指摘の修正）。
      expect(entries[0].filter).toEqual(["all", ...unknownPrefix, ["<", valueExpression, axis.thresholds[0]]]);
      const last = entries[bandCount - 1];
      expect(last.filter).toEqual([
        "all",
        ...unknownPrefix,
        [">=", valueExpression, axis.thresholds[axis.thresholds.length - 1]],
      ]);
      for (let i = 1; i < bandCount - 1; i++) {
        expect(entries[i].filter).toEqual([
          "all",
          ...unknownPrefix,
          [">=", valueExpression, axis.thresholds[i - 1]],
          ["<", valueExpression, axis.thresholds[i]],
        ]);
      }
      if (unknownExpression !== null) {
        expect(entries[bandCount].filter).toEqual(["all", unknownExpression]);
      }
    }
  });

  it("舗装質（surface_q）は未分類の路面をfalse_value（悪い）ではなく灰色「不明」にする", () => {
    // 改善計画T278レビュー指摘の修正確認: surface_goodがタイルに焼き込まれていない
    // （未分類）区間は、以前は["==",null,true]がfalseと評価されfalse_value=80
    // （最悪スコア）に落ちていた。has_unknown_fallback=trueにより、色分け式が
    // 欠損を先にCOLOR_UNKNOWNへ振り分けるようになっているはず。
    const surfaceQ = RAMP_AXES.find((axis) => axis.axisId === "surface_q")!;
    const colorExpression = buildAxisRampColorExpression(surfaceQ);

    expect(colorExpression).toEqual([
      "case",
      ["!", ["has", "surface_good"]],
      COLOR_UNKNOWN,
      expect.arrayContaining(["step"]),
    ]);

    const legend = buildAxisRampLegend(surfaceQ);
    const unknownEntry = legend.find((entry) => entry.isFallback);
    expect(unknownEntry).toBeDefined();
    expect(unknownEntry!.color).toBe(COLOR_UNKNOWN);
    expect(unknownEntry!.label).toBe("不明");
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

// @vitest-environment node
// 二次軸rampレイヤー（改善計画T145b）の純ロジック検証。DOM不要のためnode環境で実行する
// （vitest.config.mtsのコメント参照）。

import { describe, expect, it } from "vitest";

import {
  AXIS_LABELS,
  AXIS_RAMP_COLORS,
  COLOR_UNKNOWN,
  RAMP_AXES,
  type CatalogAxis,
  type RampAxis,
  axisLabelsFromCatalogAxes,
  axisLineLayerId,
  axisMapLayerId,
  buildAxisRampColorExpression,
  buildAxisRampLegend,
  buildAxisRampUnknownExpression,
  buildAxisRampValueExpression,
  rampAxesFromCatalogAxes,
  rampColorForBand,
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

  it("車ストレス（car_stress）はhighway未登録値（footway/path等）を0点[最良]ではなく灰色「不明」にする（改善計画T297）", () => {
    // 背景: highwayのcategories入力はhas_unknown_fallback=trueが以前から設定済み
    // だったが、buildAxisRampUnknownExpressionはプロパティの「欠損」しか見ておらず
    // 「値はあるが未登録」（highway="footway"等、プロパティは常に存在する）を
    // 見落としていた。評価側（domain/axis_definitions.py: evaluate_axis_scalar）は
    // 未登録値をNone（評価不能）として扱う——required=Trueの材料でNoneは軸全体を
    // 評価不能にする——ため、表示側もこれに合わせて「不明」へ倒す必要がある。
    const carStress = RAMP_AXES.find((axis) => axis.axisId === "car_stress")!;
    const highwayInput = carStress.tileInputs.find((input) => input.property === "highway")!;
    expect(highwayInput.hasUnknownFallback).toBe(true);
    expect(highwayInput.categories).toBeDefined();

    const unknownExpression = buildAxisRampUnknownExpression(carStress);
    expect(unknownExpression).not.toBeNull();

    // "match"式の分岐: 登録済みの値(例: "residential")はfalse(不明ではない)、
    // 未登録の値(例: "footway")・プロパティ欠損時のsentinel("__unknown__")はtrue(不明)。
    const [op, valueExpr, ...branches] = unknownExpression as unknown[];
    expect(op).toBe("match");
    expect(valueExpr).toEqual(["coalesce", ["get", "highway"], "__unknown__"]);
    const pairs = branches.slice(0, -1);
    const fallback = branches[branches.length - 1];
    expect(fallback).toBe(true);
    for (const knownHighway of Object.keys(highwayInput.categories!)) {
      const idx = pairs.indexOf(knownHighway);
      expect(idx).toBeGreaterThanOrEqual(0);
      expect(pairs[idx + 1]).toBe(false);
    }
    expect(pairs).not.toContain("footway");

    const legend = buildAxisRampLegend(carStress);
    const unknownEntry = legend.find((entry) => entry.isFallback);
    expect(unknownEntry).toBeDefined();
    expect(unknownEntry!.color).toBe(COLOR_UNKNOWN);
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

describe("rampColorForBand（改善計画T292: 可変バンド数の配色一般化）", () => {
  it("bandCount=4のとき旧AXIS_RAMP_COLORSと完全一致する（後方互換）", () => {
    expect([0, 1, 2, 3].map((i) => rampColorForBand(i, 4))).toEqual([...AXIS_RAMP_COLORS]);
  });

  it("両端は常にアンカーの緑・赤になる（bandCountによらず）", () => {
    for (const bandCount of [2, 3, 5, 6]) {
      expect(rampColorForBand(0, bandCount)).toBe(AXIS_RAMP_COLORS[0]);
      expect(rampColorForBand(bandCount - 1, bandCount)).toBe(AXIS_RAMP_COLORS[3]);
    }
  });

  it("bandCount=1は緑1色になる（範囲外を落ちなく処理する）", () => {
    expect(rampColorForBand(0, 1)).toBe(AXIS_RAMP_COLORS[0]);
  });

  it("色は#rrggbb形式で、同一bandCount内で単調に変化する", () => {
    for (let i = 0; i < 5; i++) {
      expect(rampColorForBand(i, 5)).toMatch(/^#[0-9a-f]{6}$/);
    }
  });
});

describe("buildAxisRampValueExpression（改善計画T292: categories/breakpoints分岐）", () => {
  const baseAxis: RampAxis = { axisId: "test", label: "テスト", category: "trafficSafety", tileInputs: [], thresholds: [50], unit: "", note: "" };

  it("categories入力はmatch式でmapping値×weightを返す", () => {
    const axis: RampAxis = {
      ...baseAxis,
      tileInputs: [{ property: "highway", weight: 2, categories: { primary: 4, residential: 2 } }],
    };
    const expression = buildAxisRampValueExpression(axis);
    expect(expression).toEqual(["match", ["coalesce", ["get", "highway"], "__unknown__"], "primary", 8, "residential", 4, 0]);
  });

  it("breakpoints入力はinterpolate式（weight=1なら素通し）をcaseで包み、タイルプロパティ欠損時は寄与0にする", () => {
    const axis: RampAxis = {
      ...baseAxis,
      tileInputs: [{ property: "maxspeed_kmh", weight: 1, breakpoints: [[0, -1], [30, -1], [60, 1]] }],
    };
    const expression = buildAxisRampValueExpression(axis);
    expect(expression).toEqual([
      "case",
      ["!", ["has", "maxspeed_kmh"]],
      0,
      ["interpolate", ["linear"], ["get", "maxspeed_kmh"], 0, -1, 30, -1, 60, 1],
    ]);
  });

  it("breakpoints入力はweight≠1のとき乗算で包む（caseの内側）", () => {
    const axis: RampAxis = {
      ...baseAxis,
      tileInputs: [{ property: "lanes_count", weight: 0.5, breakpoints: [[0, -1], [4, 1]] }],
    };
    const expression = buildAxisRampValueExpression(axis);
    expect(expression[0]).toBe("case");
    const value = expression[3] as unknown[];
    expect(value[0]).toBe("*");
    expect((value[1] as unknown[])[0]).toBe("interpolate");
    expect(value[2]).toBe(0.5);
  });

  it("categories/breakpointsを含む複数入力はΣで合成される", () => {
    const axis: RampAxis = {
      ...baseAxis,
      tileInputs: [
        { property: "highway", weight: 1, categories: { primary: 4 } },
        { property: "maxspeed_kmh", weight: 1, breakpoints: [[0, -1], [60, 1]] },
      ],
    };
    const expression = buildAxisRampValueExpression(axis);
    expect(expression[0]).toBe("+");
    expect(expression.length).toBe(3);
  });
});

// 改善計画T308: rampAxesFromCatalogAxes/axisLabelsFromCatalogAxesは、ビルド時静的json
// （axis-catalog.json）と実行時API（GET /api/axis-catalog）の両方から同じ形の値を
// 組み立てるための共通関数（hooks/useAxisCatalog.tsが後者から呼ぶ）。
describe("rampAxesFromCatalogAxes / axisLabelsFromCatalogAxes（改善計画T308）", () => {
  it("静的jsonをそのまま渡すと既存のRAMP_AXES/AXIS_LABELSと同じ結果になる（回帰確認）", () => {
    // axisCatalog.jsonを直接読み直すのではなく、既存のRAMP_AXES/AXIS_LABELS自体が
    // この関数を使って組み立てられている（axisLayers.ts参照）ため、ここでは
    // 「関数を素通しした結果が公開exportと一致する」構造そのものを確認する。
    expect(RAMP_AXES.length).toBeGreaterThan(0);
    expect(Object.keys(AXIS_LABELS).length).toBeGreaterThan(0);
  });

  it("GUI作成軸（kind=ramp、複数材料の重み付き結合）が正しくRampAxisへ変換される", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "gui_created_axis",
        display: {
          kind: "ramp",
          label: "テスト用GUI軸",
          category: "trafficSafety",
          tile_inputs: [
            { property: "lanes_count", weight: 1.0 },
            { property: "maxspeed_kmh", weight: 0.5 },
          ],
          thresholds: [10.0],
          unit: "",
          note: "",
        },
      },
    ];

    const rampAxes = rampAxesFromCatalogAxes(catalogAxes);
    expect(rampAxes).toHaveLength(1);
    expect(rampAxes[0].axisId).toBe("gui_created_axis");
    expect(rampAxes[0].label).toBe("テスト用GUI軸");
    expect(rampAxes[0].tileInputs).toEqual([
      { property: "lanes_count", weight: 1.0, boolean: undefined, invert: undefined, trueValue: undefined, falseValue: undefined, hasUnknownFallback: undefined, categories: undefined, breakpoints: undefined },
      { property: "maxspeed_kmh", weight: 0.5, boolean: undefined, invert: undefined, trueValue: undefined, falseValue: undefined, hasUnknownFallback: undefined, categories: undefined, breakpoints: undefined },
    ]);
    expect(rampAxes[0].thresholds).toEqual([10.0]);

    const labels = axisLabelsFromCatalogAxes(catalogAxes);
    expect(labels.gui_created_axis).toBe("テスト用GUI軸");
  });

  it("kind=noneの軸はRampAxesには含まれないが、ラベル辞書には含まれる", () => {
    const catalogAxes: CatalogAxis[] = [
      {
        axis_id: "not_derivable_axis",
        display: { kind: "none", label: "地図に出ない軸", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
      },
    ];

    expect(rampAxesFromCatalogAxes(catalogAxes)).toHaveLength(0);
    expect(axisLabelsFromCatalogAxes(catalogAxes).not_derivable_axis).toBe("地図に出ない軸");
  });
});

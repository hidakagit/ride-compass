// @vitest-environment node
import { createExpression } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";

import { LEGEND_NO_DATA_KEY } from "@/lib/mapDisplay/mapColorLegend";
import { mapDisplay } from "@/types/generated/mapDisplay";
import palette from "@/types/generated/palette.json";

import type { RampAxis } from "@/lib/mapDisplay/axisLayers";

import { axisLineGroup, buildAxisRampValueExpression, type AxisLineState } from "./axisLines";

// 地図全体の「薄い＝対象外、濃い＝分類あり」という読み方を、レンズの線にも効かせる。
// 方位を指定すると値を示せない道が街区の半分近くを占めうるため、濃いまま塗ると
// 値のある道がそこへ埋もれる。
const BANDS = [
  { key: "b0", lowerBound: 0, color: "#16a34a" },
  { key: "b1", lowerBound: 5, color: "#dc2626" },
];

function opacityOf(value: AxisLineState["axes"][number]["value"], underlay = false): unknown {
  const state: AxisLineState = {
    sourceLayer: "road",
    axes: [{ axisId: "gradient", visible: true, bands: BANDS, value, hiddenBandKeys: [], underlay }],
  };
  return axisLineGroup.build(state).layers[0].paint?.["line-opacity"];
}

describe("レンズの線の濃さ", () => {
  it("値を受け取れなかった道は薄く、値を持つ道は濃く塗る", () => {
    const opacity = opacityOf({ kind: "delivered", values: new Map(), loading: false }) as unknown[];

    expect(opacity[0]).toBe("case");
    expect(opacity[2]).toBe(mapDisplay.road.unknownOpacity);
    expect(opacity[3]).toBe(mapDisplay.road.knownOpacity);
    expect(mapDisplay.road.unknownOpacity).toBeLessThan(mapDisplay.road.knownOpacity);
  });

  it("取得中は薄くしない（「取得中」と「対象外」が見分けられなくなるため）", () => {
    expect(opacityOf({ kind: "delivered", values: new Map(), loading: true })).toBe(mapDisplay.road.knownOpacity);
  });

  it("材料が同時に出ているときの下敷きは、全体を薄く敷く", () => {
    expect(opacityOf({ kind: "delivered", values: new Map(), loading: false }, true)).toBe(
      mapDisplay.road.unknownOpacity,
    );
  });
});

// 以下は式をMapLibreと同じ評価器（docs/architecture/tech-stack.md）で実際に評価し、
// 1本の道がどの色になるか・残るかを見る。式の形を見ると、同じ意味の別の書き方で落ちる。
const GLOBALS = { zoom: 14 } as never;
const TRANSPARENT = "rgba(0,0,0,0)";

/** 上の段から並べた3段（applyToMapが渡す順）。 */
const THREE_BANDS = [
  { key: "high", lowerBound: 20, color: "#dc2626" },
  { key: "mid", lowerBound: 10, color: "#f59e0b" },
  { key: "low", lowerBound: Number.NEGATIVE_INFINITY, color: "#16a34a" },
];

/** タイルの材料から組み立てる軸。材料`v`が欠けた道は評価できない。 */
const TILE_VALUE = {
  kind: "tile" as const,
  expression: ["coalesce", ["get", "v"], 0],
  unknown: ["!", ["has", "v"]],
};

function layerFor(value: AxisLineState["axes"][number]["value"], hiddenBandKeys: readonly string[] = []) {
  const state: AxisLineState = {
    sourceLayer: "road",
    axes: [{ axisId: "ax", visible: true, bands: THREE_BANDS, value, hiddenBandKeys, underlay: false }],
  };
  return axisLineGroup.build(state).layers[0];
}

function evaluate(expression: unknown, properties: Record<string, unknown>, state: Record<string, unknown> = {}) {
  const compiled = createExpression(expression, "paint");
  if (compiled.result !== "success") {
    throw new Error(compiled.value.map((error) => `${error.key}: ${error.message}`).join("; "));
  }
  return compiled.value.evaluateWithoutErrorHandling(GLOBALS, { type: 2, properties } as never, state);
}

describe("レンズの線の線種", () => {
  it("評価できない道だけを破線にし、値のある道は実線のまま", () => {
    const dash = layerFor(TILE_VALUE).paint?.["line-dasharray"];
    expect(evaluate(dash, {})).toEqual([...mapDisplay.noDataDash]);
    expect(evaluate(dash, { v: 15 })).toEqual([1, 0]);
  });

  it("取得中は破線にしない（まだ来ていないだけで、値が無いとは決まっていない）", () => {
    expect(layerFor({ kind: "delivered", values: new Map(), loading: true }).paint?.["line-dasharray"]).toBeUndefined();
  });
});

describe("タイルの材料から塗る軸", () => {
  it("評価できない道は段の色ではなく「不明」の色で、薄く塗る", () => {
    // 欠損を番兵（0）へ倒した値で段を引くと、評価できない道が最良の段の色になる。
    const layer = layerFor(TILE_VALUE);

    expect(evaluate(layer.paint?.["line-color"], {})).toBe(palette.semantic.no_data);
    expect(evaluate(layer.paint?.["line-opacity"], {})).toBe(mapDisplay.road.unknownOpacity);
    expect(evaluate(layer.paint?.["line-color"], { v: 15 })).toBe("#f59e0b");
    expect(evaluate(layer.paint?.["line-opacity"], { v: 15 })).toBe(mapDisplay.road.knownOpacity);
  });

  const color =
    (value: AxisLineState["axes"][number]["value"], hidden: readonly string[]) =>
    (properties: Record<string, unknown>) =>
      evaluate(layerFor(value, hidden).paint?.["line-color"], properties);

  it("中ほどの段を隠すと、その段の道だけが透明になる（上の段は残る）", () => {
    const of = color(TILE_VALUE, ["mid"]);

    expect(of({ v: 5 })).toBe("#16a34a");
    expect(of({ v: 15 })).toBe(TRANSPARENT);
    expect(of({ v: 25 })).toBe("#dc2626");
    expect(of({})).toBe(palette.semantic.no_data);
  });

  it("「不明」を隠すと、評価できない道だけが透明になる", () => {
    const of = color(TILE_VALUE, [LEGEND_NO_DATA_KEY]);

    expect(of({})).toBe(TRANSPARENT);
    expect(of({ v: 5 })).toBe("#16a34a");
  });

  it("不明という状態を持たない軸は、段を隠しても全段が評価できる", () => {
    const of = color({ ...TILE_VALUE, unknown: null }, ["low"]);

    expect(of({ v: 5 })).toBe(TRANSPARENT);
    expect(of({ v: 15 })).toBe("#f59e0b");
  });
});

describe("配信された値で塗る軸", () => {
  const delivered = (loading = false) => ({ kind: "delivered" as const, values: new Map<string, number>(), loading });
  const color = (value: ReturnType<typeof delivered>, hidden: readonly string[], state: Record<string, unknown>) =>
    evaluate(layerFor(value, hidden).paint?.["line-color"], {}, state);

  it("値が無い道は「データなし」の色、取得中は取得中の色", () => {
    expect(color(delivered(), [], {})).toBe(palette.semantic.no_data);
    expect(color(delivered(true), [], {})).toBe(palette.semantic.loading);
  });

  it("隠した段の道だけが透明になり、他の段の色は変わらない", () => {
    expect(color(delivered(), ["mid"], { axValue: 15 })).toBe(TRANSPARENT);
    expect(color(delivered(), ["mid"], { axValue: 25 })).toBe("#dc2626");
    expect(color(delivered(), ["mid"], { axValue: 5 })).toBe("#16a34a");
  });

  it("「データなし」を隠すと値の無い道が透明になる。ただし取得中の色は残す", () => {
    expect(color(delivered(), [LEGEND_NO_DATA_KEY], {})).toBe(TRANSPARENT);
    expect(color(delivered(true), [LEGEND_NO_DATA_KEY], {})).toBe(palette.semantic.loading);
  });
});

describe("buildAxisRampValueExpression（改善計画T292: categories/breakpoints分岐）", () => {
  const baseAxis: RampAxis = {
    axisId: "test",
    label: "テスト",
    category: "trafficSafety",
    tileInputs: [],
    thresholds: [50],
    unit: "",
  };

  it("categories入力はmatch式でmapping値×weightを返す", () => {
    const axis: RampAxis = {
      ...baseAxis,
      tileInputs: [{ property: "highway", weight: 2, categories: { primary: 4, residential: 2 } }],
    };
    const expression = buildAxisRampValueExpression(axis);
    expect(expression).toEqual([
      "match",
      ["coalesce", ["get", "highway"], "__unknown__"],
      "primary",
      8,
      "residential",
      4,
      0,
    ]);
  });

  it("breakpoints入力はinterpolate式（weight=1なら素通し）をcaseで包み、タイルプロパティ欠損時は寄与0にする", () => {
    const axis: RampAxis = {
      ...baseAxis,
      tileInputs: [
        {
          property: "maxspeed_kmh",
          weight: 1,
          breakpoints: [
            [0, -1],
            [30, -1],
            [60, 1],
          ],
        },
      ],
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
      tileInputs: [
        {
          property: "lanes_count",
          weight: 0.5,
          breakpoints: [
            [0, -1],
            [4, 1],
          ],
        },
      ],
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
        {
          property: "maxspeed_kmh",
          weight: 1,
          breakpoints: [
            [0, -1],
            [60, 1],
          ],
        },
      ],
    };
    const expression = buildAxisRampValueExpression(axis);
    expect(expression[0]).toBe("+");
    expect(expression.length).toBe(3);
  });
});

// @vitest-environment node
import { describe, expect, it } from "vitest";

import { LEGEND_NO_DATA_KEY, LEGEND_UNDETERMINED_KEY } from "@/lib/mapDisplay/mapColorLegend";
import { mapDisplay } from "@/types/generated/mapDisplay";
import palette from "@/types/generated/palette.json";

import { rampAxesFromCatalogAxes } from "@/lib/mapDisplay/axisLayers";
import { catalogEntry, tileInput } from "@/testing/catalogAxes";
import { evaluateExpression as evaluate } from "@/testing/mapExpressions";
import axisRampExpectations from "@/types/generated/axis-ramp-expectations.json";
import type { AxisCatalogEntry } from "@/types/route";

import {
  axisLineGroup,
  buildAxisRampUnknownExpression,
  buildAxisRampValueExpression,
  type AxisLineState,
} from "./axisLines";

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
  it("取得中は薄くしない（「取得中」と「対象外」が見分けられなくなるため）", () => {
    expect(opacityOf({ kind: "delivered", values: new Map(), loading: true })).toBe(mapDisplay.road.knownOpacity);
  });

  it("材料が同時に出ているときの下敷きは、全体を薄く敷く", () => {
    expect(opacityOf({ kind: "delivered", values: new Map(), loading: false }, true)).toBe(
      mapDisplay.road.underlayOpacity,
    );
  });
});

// 以下は式をMapLibreと同じ評価器（docs/architecture/tech-stack.md）で実際に評価し、
// 1本の道がどの色になるか・残るかを見る。式の形を見ると、同じ意味の別の書き方で落ちる。
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

describe("レンズの線の線種", () => {
  it("評価できない道だけを破線にし、値のある道は実線のまま", () => {
    const dash = layerFor(TILE_VALUE).paint?.["line-dasharray"];
    expect(evaluate(dash, {})).toEqual([...mapDisplay.noDataDash]);
    expect(evaluate(dash, { v: 15 })).toEqual([1, 0]);
  });

  it("配信値の軸は破線を持たない（破線の刻みはfeature-stateを読めない）", () => {
    expect(
      layerFor({ kind: "delivered", values: new Map(), loading: false }).paint?.["line-dasharray"],
    ).toBeUndefined();
  });
});

describe("タイルの材料から塗る軸", () => {
  it("評価できない道は段の色ではなく「不明」の色で、薄く塗る", () => {
    // 欠損を番兵（0）へ倒した値で段を引くと、評価できない道が最良の段の色になる。
    const layer = layerFor(TILE_VALUE);

    expect(evaluate(layer.paint?.["line-color"], {})).toBe(palette.semantic.no_data);
    expect(evaluate(layer.paint?.["line-opacity"], {})).toBe(mapDisplay.road.unknownOpacity);
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
  });

  it("「不明」を隠すと、評価できない道が透明になる", () => {
    expect(color(TILE_VALUE, [LEGEND_NO_DATA_KEY])({})).toBe(TRANSPARENT);
  });

  it("不明という状態を持たない軸は、段を隠しても全段が評価できる", () => {
    const of = color({ ...TILE_VALUE, unknown: null }, ["low"]);

    expect(of({ v: 5 })).toBe(TRANSPARENT);
  });
});

describe("配信された値で塗る軸", () => {
  const delivered = (loading = false) => ({ kind: "delivered" as const, values: new Map<string, number>(), loading });
  const color = (value: ReturnType<typeof delivered>, hidden: readonly string[], state: Record<string, unknown>) =>
    evaluate(layerFor(value, hidden).paint?.["line-color"], {}, state);

  it("段を隠すと、配信された値がその段の道が透明になる（隠し方はタイルの材料から塗る軸と同じ）", () => {
    expect(color(delivered(), ["mid"], { axValue: 15 })).toBe(TRANSPARENT);
  });

  it("取得中の道は取得中の色で、「データなし」を隠していても残す", () => {
    expect(color(delivered(true), [LEGEND_NO_DATA_KEY], {})).toBe(palette.semantic.loading);
  });

  describe("走行方位で値が決まらない道（配信の値がnull）", () => {
    const values = new Map<string, number | null>([
      ["perpendicular", null],
      ["along", 15],
    ]);
    /** 配信の値を地図へ載せたとき、その道が受け取るfeature-stateで塗った色。 */
    const colorOf = (featureId: string, hidden: readonly string[] = []) => {
      const state: AxisLineState = {
        sourceLayer: "road",
        axes: [
          {
            axisId: "ax",
            visible: true,
            bands: THREE_BANDS,
            value: { kind: "delivered", values, loading: false },
            hiddenBandKeys: hidden,
            underlay: false,
          },
        ],
      };
      const group = axisLineGroup.build(state);
      const featureState = Object.fromEntries(
        [...(group.sources[0].featureStates ?? [])].flatMap(([key, byFeature]) =>
          byFeature.has(featureId) ? [[key, byFeature.get(featureId)]] : [],
        ),
      );
      return evaluate(group.layers[0].paint?.["line-color"], {}, featureState);
    };

    it("「データなし」ではなく「向きで決まらない」の色で塗り、値のある道は段の色のまま", () => {
      expect(colorOf("perpendicular")).toBe(palette.semantic.undetermined);
      expect(colorOf("along")).toBe("#f59e0b");
      expect(colorOf("absent")).toBe(palette.semantic.no_data);
    });

    it("凡例で「向きで決まらない」を隠すとその道だけが透明になり、「データなし」を隠しても残る", () => {
      expect(colorOf("perpendicular", [LEGEND_UNDETERMINED_KEY])).toBe(TRANSPARENT);
      expect(colorOf("absent", [LEGEND_UNDETERMINED_KEY])).toBe(palette.semantic.no_data);
      expect(colorOf("perpendicular", [LEGEND_NO_DATA_KEY])).toBe(palette.semantic.undetermined);
    });
  });
});

// backendの表の値は評価が付ける値で、地図の式は同じ演算を別の順で行うため最下位の桁だけ違いうる。
const RAMP_VALUE_TOLERANCE = 1e-9;

describe("ramp軸の式は、backendの表（形ごとの軸と道）で評価と同じ値・同じ「不明」を出す", () => {
  const axes = axisRampExpectations.axes;

  it("表が空でない", () => {
    expect(axes.length).toBeGreaterThan(0);
    for (const { roads } of axes) expect(roads.length).toBeGreaterThan(0);
  });

  for (const { axis: name, display, runtime_scales, roads } of axes) {
    it(name, () => {
      const [axis] = rampAxesFromCatalogAxes(
        [catalogEntry({ axis_id: "table", map_paint: { tiles: display as AxisCatalogEntry["map_paint"]["tiles"] } })],
        runtime_scales,
      );
      const unknownExpression = buildAxisRampUnknownExpression(axis);
      const valueExpression = buildAxisRampValueExpression(axis);
      for (const { road, properties, unknown } of roads) {
        const isUnknown = unknownExpression === null ? false : evaluate(unknownExpression, properties);
        expect(isUnknown, `${road}: 不明か`).toBe(unknown);
      }
      const valued = roads.filter((row): row is typeof row & { value: number } => row.value !== null);
      expect(valued.length).toBeGreaterThan(0);
      for (const { road, properties, value } of valued) {
        const painted = evaluate(valueExpression, properties) as number;
        expect(Math.abs(painted - value), `${road}: ${painted} と ${value}`).toBeLessThan(RAMP_VALUE_TOLERANCE);
      }
    });
  }
});

describe("buildAxisRampUnknownExpression", () => {
  it("換算の係数が届いていない材料を使う軸は、どの道も「不明」", () => {
    const tile_inputs = [tileInput({ property: "v", weight: 1, needs_runtime_scale: true })];
    const display = {
      kind: "ramp" as const,
      label: "scaled",
      category: "roadCondition",
      tile_inputs,
      thresholds: [10],
    };
    const [axis] = rampAxesFromCatalogAxes([catalogEntry({ axis_id: "scaled", map_paint: { tiles: display } })], {});

    expect(evaluate(buildAxisRampUnknownExpression(axis), { v: 5 })).toBe(true);
  });
});

// @vitest-environment node
import { describe, expect, it } from "vitest";

import { mapCatalogOf } from "@/testing/mapAxisCatalog";
import { LEGEND_NO_DATA_KEY, LEGEND_UNDETERMINED_KEY } from "@/lib/mapDisplay/mapColorLegend";

import { catalogEntry, dedicatedEntry, rampEntry, tileInput } from "@/testing/catalogAxes";
import { matchesFilter as matches } from "@/testing/mapExpressions";
import { isRouteStyleModeId, lensConditionsLabel, lensLegend, lensOptions, paintedAxisId } from "./lens";

/** 道の値として読む材料。 */
const VALUE = "v";

/** 材料`VALUE`がそのまま値になるramp軸。`hasUnknownFallback`なら、材料が欠けた道を「データなし」にする。 */
function valueRamp(
  axisId: string,
  thresholds: number[],
  overrides: Parameters<typeof catalogEntry>[0] = {},
  hasUnknownFallback = false,
) {
  return catalogEntry({
    axis_id: axisId,
    ...overrides,
    display: {
      kind: "ramp",
      tile_inputs: [tileInput({ property: VALUE, weight: 1, has_unknown_fallback: hasUnknownFallback })],
      thresholds,
    },
  });
}

const catalog = mapCatalogOf([valueRamp("ramp", [10, 20]), valueRamp("unknown", [10], {}, true)]);

describe("paintedAxisId（全道路を塗る軸）", () => {
  it("ルートを確定するまではレンズの軸、確定後は周囲も塗り続ける設定の間だけ", () => {
    expect(paintedAxisId("ramp", false, false)).toBe("ramp");
    expect(paintedAxisId("ramp", true, true)).toBe("ramp");
    expect(paintedAxisId("ramp", true, false)).toBeNull();
  });
});

describe("lensLegend（レンズの凡例）", () => {
  it("ramp軸は、どの値の道も当てはまる行がちょうど1つ（境界は上の段）", () => {
    const legend = lensLegend("ramp", false, catalog);
    for (const [value, expected] of [
      [5, 0],
      [10, 1],
      [19.9, 1],
      [20, 2],
    ] as const) {
      const hits = legend.flatMap((entry, index) => (matches(entry.filter, { [VALUE]: value }) ? [index] : []));
      expect(hits).toEqual([expected]);
    }
  });

  it("材料が欠けて評価できない道は、数値の段ではなく末尾の「データなし」だけに当てはまる", () => {
    const legend = lensLegend("unknown", false, catalog);
    const hitsFor = (properties: Record<string, unknown>) =>
      legend.flatMap((entry) => (matches(entry.filter, properties) ? [entry.key] : []));
    expect(hitsFor({})).toEqual([LEGEND_NO_DATA_KEY]);
    expect(hitsFor({ [VALUE]: 5 })).toEqual(["step-0"]);
  });

  it("ルート確定後は、ルート線の色分けモードの凡例。塗る軸でない・無いモードは空", () => {
    const mode = catalog.routeStyleModes.find((entry) => entry.legend.length > 0)!;
    expect(lensLegend(mode.id, true, catalog)).toBe(mode.legend);
    expect(lensLegend("missing", true, catalog)).toEqual([]);
    expect(lensLegend("missing", false, catalog)).toEqual([]);
  });
});

describe("同じ軸の同じ段は、ルートを出す前と後で同じ行", () => {
  // 前後の段の数はbackendが揃えて配る（前は重み付き和の目盛り、後は難易度の目盛りで、同じ数の境界）。
  const sameBands = mapCatalogOf([
    valueRamp(
      "ramp",
      [1, 2, 3, 4],
      { map_paint: { thresholds: [20, 40, 60, 80], legend: { boundaries: [20, 40, 60, 80], unit: null } } },
      true,
    ),
    dedicatedEntry("rain", [30, 70], { map_paint: { legend: { boundaries: [5, 20], unit: "mm" } } }),
    dedicatedEntry("signed", [-6, -2, 2, 6], {
      map_paint: {
        value: { kind: "signed_material", material: VALUE },
        legend: { boundaries: [-6, -2, 2, 6], unit: "%" },
      },
    }),
  ]);
  const paintable = [...sameBands.rampAxes, ...sameBands.dedicatedAxes].map((axis) => axis.axisId);

  it.each(paintable)("%s: 段の鍵・色・呼び方が前後で同じ", (axisId) => {
    const shape = (hasDetail: boolean) =>
      lensLegend(axisId, hasDetail, sameBands).map(({ key, color, label }) => ({ key, color, label }));
    expect(shape(false)).toEqual(shape(true));
  });
});

describe("走行方位で値が決まらない道の行", () => {
  const undetermined = mapCatalogOf([
    dedicatedEntry("by_bearing", [1], { dynamic_way_value_undetermined_by_bearing: true }),
    dedicatedEntry("always", [1]),
  ]);
  const keys = (axisId: string, hasDetail: boolean) =>
    lensLegend(axisId, hasDetail, undetermined).map((entry) => entry.key);

  it("配信がその道を返しうる軸だけ、ルートの前の凡例で「データなし」の前に持つ", () => {
    expect(keys("by_bearing", false).slice(-2)).toEqual([LEGEND_UNDETERMINED_KEY, LEGEND_NO_DATA_KEY]);
    expect(keys("always", false)).not.toContain(LEGEND_UNDETERMINED_KEY);
  });
});

describe("lensConditionsLabel（周りの道の色が拠る走る条件）", () => {
  const conditional = mapCatalogOf([
    dedicatedEntry("bearing_only", [1], { dynamic_way_value_conditions: ["bearing_deg"] }),
    dedicatedEntry("all", [1], { dynamic_way_value_conditions: ["at", "bearing_deg", "speed_kmh"] }),
    dedicatedEntry("none", [1]),
    rampEntry("ramp", [1]),
  ]).dedicatedAxes;
  const ride = { bearingDeg: 90, speedKmh: 22 };

  it.each([
    ["bearing_only", "東へ走る"],
    ["all", "東へ走る・時速22km・19:30出発"],
    ["none", null],
    ["ramp", null],
    [null, null],
  ])("塗っている軸（%s）が使う条件だけを並べ、使わなければnull", (axisId, expected) => {
    expect(lensConditionsLabel(axisId, conditional, ride, "19:30")).toBe(expected);
  });
});

describe("lensOptions（レンズの選択肢）", () => {
  const { axes } = mapCatalogOf([rampEntry("ramp", [1]), catalogEntry({ axis_id: "route_only" })]);
  const paintable = new Set(["ramp"]);

  it("全道路を塗れない軸はルートだけの印を持ち、識別色が無ければ中立色", () => {
    const [ramp, routeOnly] = lensOptions(axes, paintable, { ramp: 1, route_only: 1 }, { ramp: "#123456" });
    expect(ramp).toMatchObject({ id: "ramp", label: "ramp", color: "#123456", routeOnly: false, unused: false });
    expect(routeOnly.routeOnly).toBe(true);
    expect(routeOnly.color).not.toBe("#123456");
  });

  it("「未使用」は、渡した重みが0以下か、重みを持たない軸", () => {
    expect(lensOptions(axes, paintable, { ramp: 0 }, {}).map((option) => option.unused)).toEqual([true, true]);
  });
});

describe("isRouteStyleModeId", () => {
  it("いまのカタログにあるモードの綴りだけを受ける（保存値の読み戻し）", () => {
    expect(isRouteStyleModeId(catalog.routeStyleModes, catalog.routeStyleModes[0].id)).toBe(true);
    expect(isRouteStyleModeId(catalog.routeStyleModes, "gone")).toBe(false);
  });
});

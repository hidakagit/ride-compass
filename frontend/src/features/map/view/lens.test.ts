// @vitest-environment node
import { featureFilter, type FilterSpecification } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";

import { LEGEND_NO_DATA_KEY } from "@/lib/mapDisplay/mapColorLegend";
import { DEFAULT_DIFFICULTY_BOUNDARIES } from "@/lib/mapDisplay/valueScale";

import {
  catalogEntry,
  catalogOf,
  dedicatedEntry,
  rampEntry,
  tileInput,
} from "@/lib/mapDisplay/__fixtures__/catalogAxes";
import { isRouteStyleModeId, lensLegend, lensOptions, paintedAxisId } from "./lens";

/** 道の値として読む材料。 */
const VALUE = "v";

/** 材料`VALUE`がそのまま値になるramp軸。`hasUnknownFallback`なら、材料が欠けた道を「不明」にする。 */
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
      label: axisId,
      category: "roadCondition",
      tile_inputs: [tileInput({ property: VALUE, weight: 1, has_unknown_fallback: hasUnknownFallback })],
      thresholds,
    },
  });
}

const catalog = catalogOf([
  valueRamp("ramp", [10, 20], { raw_value_unit: "%" }),
  rampEntry("labelled", [10], { display_band_labels_override: ["平ら", "坂"] }),
  rampEntry("mislabelled", [10], { display_band_labels_override: ["1つだけ"] }),
  valueRamp("unknown", [10], {}, true),
  dedicatedEntry("dedicated", [1, 3], { map_value_unit: "m/s" }),
  dedicatedEntry("defaults", [], { map_value_thresholds: null }),
]);

/** 凡例の行の述語が、その値の道に当てはまるか（MapLibreと同じ評価器で評価する）。 */
function matches(filter: unknown, properties: Record<string, unknown>): boolean {
  return featureFilter(filter as FilterSpecification, "filter").filter(
    { zoom: 14 } as never,
    {
      type: 2,
      properties,
    } as never,
  );
}

describe("paintedAxisId（全道路を塗る軸）", () => {
  it("ルートを確定するまではレンズの軸、確定後は周囲も塗り続ける設定の間だけ", () => {
    expect(paintedAxisId("ramp", false, false)).toBe("ramp");
    expect(paintedAxisId("ramp", true, true)).toBe("ramp");
    expect(paintedAxisId("ramp", true, false)).toBeNull();
  });
});

describe("lensLegend（レンズの凡例）", () => {
  it("ramp軸は、どの値の道も当てはまる行がちょうど1つ（境界は上の段）で、範囲を単位つきで名乗る", () => {
    const legend = lensLegend("ramp", false, catalog);
    expect(legend.map((entry) => entry.label)).toEqual(["10%未満", "10〜20%", "20%以上"]);
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

  it("段の鍵は軸idを含まず、ルート確定後の凡例と同じ綴り", () => {
    expect(lensLegend("ramp", false, catalog).map((entry) => entry.key)).toEqual(["step-0", "step-1", "step-2"]);
  });

  it("体感ラベルは段数と一致するときだけ添える", () => {
    expect(lensLegend("labelled", false, catalog).map((entry) => entry.label)).toEqual([
      "平ら（10未満）",
      "坂（10以上）",
    ]);
    expect(lensLegend("mislabelled", false, catalog).map((entry) => entry.label)).toEqual(["10未満", "10以上"]);
  });

  it("材料が欠けて評価できない道は、数値の段ではなく末尾の「不明」だけに当てはまる", () => {
    const legend = lensLegend("unknown", false, catalog);
    expect(legend.at(-1)).toMatchObject({ key: LEGEND_NO_DATA_KEY, label: "不明", isFallback: true });
    const hitsFor = (properties: Record<string, unknown>) =>
      legend.flatMap((entry) => (matches(entry.filter, properties) ? [entry.key] : []));
    expect(hitsFor({})).toEqual([LEGEND_NO_DATA_KEY]);
    expect(hitsFor({ [VALUE]: 5 })).toEqual(["step-0"]);
  });

  it("専用配信軸は、配信値の境界で段を作り、末尾に値を受け取れなかった道の行を持つ", () => {
    const legend = lensLegend("dedicated", false, catalog);
    expect(legend.map((entry) => entry.label)).toEqual(["1m/s未満", "1〜3m/s", "3m/s以上", "データなし"]);
    expect(legend.at(-1)).toMatchObject({ key: LEGEND_NO_DATA_KEY, isFallback: true });
  });

  it("専用配信軸が境界を持たなければ、難易度の既定の境界で段を作る", () => {
    expect(lensLegend("defaults", false, catalog)).toHaveLength(DEFAULT_DIFFICULTY_BOUNDARIES.length + 2);
  });

  it("ルート確定後は、ルート線の色分けモードの凡例。塗る軸でない・無いモードは空", () => {
    const mode = catalog.routeStyleModes.find((entry) => entry.legend.length > 0)!;
    expect(lensLegend(mode.id, true, catalog)).toBe(mode.legend);
    expect(lensLegend("missing", true, catalog)).toEqual([]);
    expect(lensLegend("missing", false, catalog)).toEqual([]);
  });
});

describe("lensOptions（レンズの選択肢）", () => {
  const { axes } = catalogOf([rampEntry("ramp", [1]), catalogEntry({ axis_id: "route_only" })]);
  const paintable = new Set(["ramp"]);

  it("全道路を塗れない軸はルートだけの印を持ち、識別色が無ければ中立色", () => {
    const [ramp, routeOnly] = lensOptions(axes, paintable, null, { ramp: "#123456" });
    expect(ramp).toMatchObject({ id: "ramp", label: "ramp", color: "#123456", routeOnly: false, unused: false });
    expect(routeOnly.routeOnly).toBe(true);
    expect(routeOnly.color).not.toBe("#123456");
  });

  it("「未使用」は、生成に使った重みが0以下の軸にだけ、生成した後で付ける", () => {
    const [ramp, routeOnly] = lensOptions(axes, paintable, { ramp: 2 }, {});
    expect(ramp.unused).toBe(false);
    expect(routeOnly.unused).toBe(true);
    expect(lensOptions(axes, paintable, null, {}).some((option) => option.unused)).toBe(false);
  });
});

describe("isRouteStyleModeId", () => {
  it("いまのカタログにあるモードの綴りだけを受ける（保存値の読み戻し）", () => {
    expect(isRouteStyleModeId(catalog.routeStyleModes, catalog.routeStyleModes[0].id)).toBe(true);
    expect(isRouteStyleModeId(catalog.routeStyleModes, "gone")).toBe(false);
    expect(isRouteStyleModeId(catalog.routeStyleModes, null)).toBe(false);
  });
});

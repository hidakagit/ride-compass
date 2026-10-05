// @vitest-environment node
/**
 * `lib/mapDisplay/routeStyleModes.ts`——ルートの線の色分けのモード（レンズ）の一覧と、モードごとの色・凡例・破線の式。
 * 入口は`routeStyleModesFromCatalogAxes`。式はMapLibreと同じ評価器で区間1本へ当て（`testing/mapExpressions.ts`）、
 * その区間が何色に塗られ、凡例のどの行に入り、破線になるかを見る。軸は`testing/catalogAxes.ts`の雛形で組む。
 *
 * ここで見ないもの:
 * - 段の色・範囲の文字・体感ラベルの決め方 → `valueScale.test.ts`・`mapColorLegend.test.ts`
 * - 値で段を引く式と「データなし」の分け方は、どのモードも同じ組み立てを通るので、軸の難易度で塗るモードで両側を見て、
 *   ほかのモードはどの値で塗るかだけを見る
 * - 区間が持つ値（総合難易度・軸ごとの難易度・材料の値）を作ること → backendのルート生成のテスト
 * - モードを選ぶ画面と、選んだモードの式を地図へ渡すこと → `features/map/LensControl/LensControl.test.tsx`・
 *   `features/map/view/lens.test.ts`
 */
import { Color } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";

import { catalogEntry } from "@/testing/catalogAxes";
import { evaluateExpression, matchesFilter } from "@/testing/mapExpressions";
import palette from "@/types/generated/palette.json";

import { LEGEND_NO_DATA_KEY } from "./mapColorLegend";
import {
  LENS_DIFFICULTY_ID,
  LENS_NEUTRAL_COLOR,
  LENS_NONE_ID,
  routeStyleModesFromCatalogAxes,
  type RouteStyleMode,
} from "./routeStyleModes";
import { DEFAULT_DIFFICULTY_BOUNDARIES } from "./valueScale";

function modeOf(axes: Parameters<typeof routeStyleModesFromCatalogAxes>[0], id: string): RouteStyleMode {
  const mode = routeStyleModesFromCatalogAxes(axes).find((candidate) => candidate.id === id);
  if (mode === undefined) throw new Error(`モード${id}が無い`);
  return mode;
}

/** 区間1本の描かれ方: 塗る色・当てはまる凡例の行の鍵・破線か。 */
function drawn(mode: RouteStyleMode, segment: Record<string, unknown>) {
  return {
    color: evaluateExpression(mode.colorExpression, segment),
    rows: mode.legend.filter((row) => matchesFilter(row.filter, segment)).map((row) => row.key),
    dashed: mode.noDataExpression === undefined ? false : evaluateExpression(mode.noDataExpression, segment),
  };
}

/** 境界の手前・ちょうど・先と、両端の外の値。 */
function probeValues(boundaries: readonly number[]): number[] {
  expect(boundaries.length).toBeGreaterThan(0);
  return [boundaries[0] - 1000, ...boundaries.flatMap((b) => [b - 0.01, b, b + 0.01]), boundaries.at(-1)! + 1000];
}

/** どの値の区間も、塗った色の凡例の行1つだけに当てはまり、境界ちょうどの値は上の段に入る。 */
function expectColorsMatchLegend(
  mode: RouteStyleMode,
  boundaries: readonly number[],
  segmentOf: (v: number) => object,
) {
  const bandRows = mode.legend.filter((row) => row.key !== LEGEND_NO_DATA_KEY);
  expect(bandRows).toHaveLength(boundaries.length + 1);
  for (const value of probeValues(boundaries)) {
    const { color, rows, dashed } = drawn(mode, segmentOf(value) as Record<string, unknown>);
    const band = boundaries.filter((boundary) => value >= boundary).length;
    expect({ value, rows, color, dashed }).toEqual({
      value,
      rows: [bandRows[band].key],
      color: bandRows[band].color,
      dashed: false,
    });
  }
}

describe("モードの一覧", () => {
  it("公開軸ごとのモードをカタログの順に並べ、そのあとに総合難易度と「なし」を置く", () => {
    const modes = routeStyleModesFromCatalogAxes([catalogEntry({ axis_id: "b" }), catalogEntry({ axis_id: "a" })]);

    expect(modes.map((mode) => mode.id)).toEqual(["b", "a", LENS_DIFFICULTY_ID, LENS_NONE_ID]);
  });
});

describe("難易度で塗る軸のモード", () => {
  const axis = catalogEntry({
    axis_id: "ax",
    map_paint: { thresholds: [20, 50] },
    label: "風",
    display_band_labels_override: ["弱", "中", "強"],
  });
  const mode = modeOf([axis], "ax");
  const segmentOf = (value: unknown) => ({ axis_difficulties: { ax: value, other: 99 } });

  it("名前は「<軸の名前>の影響」で、凡例は段ごとの行（単位・体感ラベルつき）と値が無い行", () => {
    expect(mode.label).toBe("風の影響");
    expect(mode.legend.map((row) => row.label)).toEqual(["弱[20点未満]", "中[20〜50点]", "強[50点以上]", "データなし"]);
  });

  it("区間のその軸の難易度で塗り、塗った色の行だけに当てはまる", () => {
    expectColorsMatchLegend(mode, [20, 50], segmentOf);
  });

  it("難易度0の区間は最も易しい段で、値が無い区間だけが「データなし」の色の破線になる", () => {
    const lowest = mode.legend[0];
    expect(drawn(mode, segmentOf(0))).toEqual({ color: lowest.color, rows: [lowest.key], dashed: false });
    expect(drawn(mode, segmentOf(null))).toEqual({
      color: palette.semantic.no_data,
      rows: [LEGEND_NO_DATA_KEY],
      dashed: true,
    });
  });
});

describe("材料の値をそのまま塗る軸のモード（符号付き材料）", () => {
  const axis = catalogEntry({
    axis_id: "slope",
    label: "勾配",
    map_paint: {
      value: { kind: "signed_material", material: "grade" },
      thresholds: [-2, 2],
      legend: { boundaries: [-2, 2], unit: "%" },
    },
  });
  const mode = modeOf([axis], "slope");
  const segmentOf = (value: unknown) => ({ material_values: { grade: value }, axis_difficulties: { slope: 99 } });

  it("名前は軸の名前のままで、凡例の範囲は材料の単位で書く", () => {
    expect(mode.label).toBe("勾配");
    expect(mode.legend.map((row) => row.label)).toEqual(["-2%未満", "-2〜2%", "2%以上", "データなし"]);
  });

  it("軸の難易度ではなく、区間の材料の値で塗る（負の値は下りの色）", () => {
    expect(drawn(mode, segmentOf(-5)).color).toBe(palette.semantic.signed_descent);
  });
});

describe("総合難易度のモード", () => {
  const mode = modeOf([], LENS_DIFFICULTY_ID);

  it("区間の総合難易度を、難易度の既定の境界で塗る", () => {
    expectColorsMatchLegend(mode, DEFAULT_DIFFICULTY_BOUNDARIES, (difficulty) => ({ difficulty }));
  });
});

describe("「なし」のモード", () => {
  it("どの区間も中立の1色で塗り、凡例も破線も持たない", () => {
    const mode = modeOf([], LENS_NONE_ID);

    expect(drawn(mode, { difficulty: 90 })).toEqual({
      color: Color.parse(LENS_NEUTRAL_COLOR),
      rows: [],
      dashed: false,
    });
  });
});

// @vitest-environment node
import { describe, expect, it } from "vitest";
import { routeStyleModesFromCatalogAxes } from "./routeStyleModes";
import type { CatalogAxis } from "./axisLayers";
import { catalogAxis } from "@/lib/mapDisplay/__fixtures__/catalogAxes";
import { bandColorsFor } from "./valueScale";

// 色分けの組み立てが分岐する3つの形。**その分岐を起こす性質だけ**を載せる
// （軸idは軸スタジオでユーザーが決める任意の値なので、実物の名前を当てにしない）。
const signedAxis = catalogAxis({
  map_value_kind: "signed_material",
  map_value_thresholds: [-8, -4, 4, 8],
  // 符号付きで読む材料は`shape.terms[0]`が決める（この宣言が経路の分岐そのもの）。
  shape: {
    kind: "breakpoint_linear",
    terms: [{ material: "signed_value", weight: 1, required: true }],
    preprocess: "identity",
    breakpoints: [],
  },
});
const difficultyAxis = catalogAxis({ map_value_kind: "difficulty" });
const categoricalAxis = catalogAxis({
  shape: { kind: "categorical", material: "surface", mapping: { asphalt: 100 } },
});

/** 軸1本ぶんのモード。入口（軸カタログ→モード一覧）を通し、その軸のidで引く。 */
function modeFor(axis: CatalogAxis) {
  const mode = routeStyleModesFromCatalogAxes([axis]).find((candidate) => candidate.id === axis.axis_id);
  if (mode === undefined) throw new Error(`${axis.axis_id}のモードが無い`);
  return mode;
}

describe("routeStyleModes", () => {
  // 軸idを名指しせずカタログ順をそのまま期待するのは、公開軸の集合が軸スタジオ（DB）で
  // 決まり生成物の再取り込みで変わるため（GUI作成軸のidは固定値ですらない）。

  // 改善計画T466: id未検出時のmodes[0]無警告フォールバックへ警告ログを追加した回帰テスト。

  it('gradient(map_value_kind==="signed_material")はgradient_percentを符号付きのまま直接読む——軸idのハードコード分岐ではなくbackendの宣言で判定する', () => {
    expect(signedAxis.map_value_kind).toBe("signed_material");
    const mode = modeFor(signedAxis);
    expect(mode.id).toBe(signedAxis.axis_id);
    expect(mode.colorExpression[1]).toEqual(["==", ["get", "signed_value", ["get", "material_values"]], null]);
  });

  it("改善計画T440: 境界値が2個(3段階)しか無い場合でもクラッシュせず、その数に応じたラベル・色を生成する", () => {
    const axis: CatalogAxis = {
      ...signedAxis,
      axis_id: "gradient_test",
      map_value_thresholds: [0, 5],
    };
    const mode = modeFor(axis);
    expect(mode.legend.map((e) => e.key)).toEqual(["step-0", "step-1", "step-2", "nodata"]);
    expect(mode.legend.map((e) => e.label)).toEqual(["0未満", "0〜5", "5以上", "データなし"]);
  });

  it('windはmap_value_kind==="difficulty"のため難易度経路を使う（axis_difficulties経由）', () => {
    expect(difficultyAxis.map_value_kind).toBe("difficulty");
    const wind = modeFor(difficultyAxis);
    expect(wind.id).toBe(difficultyAxis.axis_id);
    expect(wind.label).toBe(`${difficultyAxis.label}の影響`);
    expect(wind.colorExpression[1]).toEqual([
      "==",
      ["get", difficultyAxis.axis_id, ["get", "axis_difficulties"]],
      null,
    ]);
  });

  it("surface_q（shape.kind==='categorical'）も通常の絶対値差難易度経路を使い、ラベルは他の動的モードと同じ汎用形式になる（roadという専用名は無い）", () => {
    expect(categoricalAxis.shape?.kind).toBe("categorical");
    const surfaceQ = modeFor(categoricalAxis);
    expect(surfaceQ.id).toBe(categoricalAxis.axis_id);
    expect(surfaceQ.label).toBe(`${categoricalAxis.label}の影響`);
    expect(surfaceQ.colorExpression[1]).toEqual([
      "==",
      ["get", categoricalAxis.axis_id, ["get", "axis_difficulties"]],
      null,
    ]);
  });

  it("段の色は境界の個数から作る（固定の色配列を持たない）", () => {
    // 色そのものは源泉が配るので値を書かない。**個数に追従すること**だけを見る。
    expect(bandColorsFor("difficulty", [])).toHaveLength(1);
    const three = bandColorsFor("difficulty", [33, 66]);
    expect(three).toHaveLength(3);
    const five = bandColorsFor("difficulty", [20, 40, 60, 80]);
    expect(five).toHaveLength(5);
    expect(new Set(five).size).toBe(5); // 全段階が異なる色になる
    expect(five[0]).toBe(three[0]);
    expect(five.at(-1)).toBe(three.at(-1));
  });

  it("軸がカタログから消える（軸スタジオでunpublish）と、対応するモードも一覧から消える", () => {
    const kept = catalogAxis({ axis_id: "kept" });
    const dropped = catalogAxis({ axis_id: "dropped" });

    const modes = routeStyleModesFromCatalogAxes([kept]);

    expect(modes.map((m) => m.id)).toEqual(["kept", "difficulty", "none"]);
    expect(modes.some((m) => m.id === dropped.axis_id)).toBe(false);
  });

  it("改善計画T440: difficultyはどの軸にも対応しないため、軸が0件でも一覧から消えない", () => {
    const modes = routeStyleModesFromCatalogAxes([]);
    expect(modes.map((m) => m.id)).toEqual(["difficulty", "none"]);
  });
});

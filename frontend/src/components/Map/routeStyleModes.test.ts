// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import * as debugLogModule from "@/lib/debugLog";
import { buildLegendFilterExpression } from "./legendFilter";
import {
  DEFAULT_ROUTE_STYLE_MODE_ID,
  getRouteStyleMode,
  isRouteStyleModeId,
  routeColorableModeFromAxis,
  routeStyleModesFromCatalogAxes,
} from "./routeStyleModes";
import { buildAxisRampLegend, rampAxesFromCatalogAxes, type CatalogAxis } from "./axisLayers";
import { CATALOG_AXES, RAMP_AXIS } from "./__fixtures__/catalogAxes";
import { interpolateColors } from "./valueScale";

/** 段階色式（`["case", noData, COLOR_NO_DATA, ["step", value, c0, b0, c1, …]]`）が
 * 実際に色を切り替える境界値。宣言ではなく組み立て結果から読むため、境界が式へ渡る
 * 途中で変換されていればその後の値が見える。 */
function steppedBoundariesOf(mode: { colorExpression: unknown[] }): number[] {
  const step = mode.colorExpression.find((part): part is unknown[] => Array.isArray(part) && part[0] === "step");
  if (!step) return [];
  return step.slice(3).filter((part): part is number => typeof part === "number");
}
// 色分けの組み立てが分岐する3つの形。**実際の公開軸を当てにしない**——公開軸はDBが
// 持ち軸スタジオで増減するため、実物を使うと「いま何が公開されているか」を検証する
// テストになる。
const gradientAxis: CatalogAxis = {
  ...RAMP_AXIS,
  axis_id: "signed_axis",
  map_value_kind: "signed_material",
  map_value_thresholds: [-8, -4, 4, 8],
};
const windAxis: CatalogAxis = { ...RAMP_AXIS, axis_id: "difficulty_axis", map_value_kind: "difficulty" };
const surfaceQAxis: CatalogAxis = {
  ...RAMP_AXIS,
  axis_id: "categorical_axis",
  shape: { kind: "categorical", material: "surface", mapping: { asphalt: 100 } },
};

describe("routeStyleModes", () => {
  // 軸idを名指しせずカタログ順をそのまま期待するのは、公開軸の集合が軸スタジオ（DB）で
  // 決まり生成物の再取り込みで変わるため（GUI作成軸のidは固定値ですらない）。

  // 改善計画T466: id未検出時のmodes[0]無警告フォールバックへ警告ログを追加した回帰テスト。

  it('gradient(map_value_kind==="signed_material")はgradient_percentを符号付きのまま直接読む——軸idのハードコード分岐ではなくbackendの宣言で判定する', () => {
    expect(gradientAxis.map_value_kind).toBe("signed_material");
    const mode = routeColorableModeFromAxis(gradientAxis);
    expect(mode.id).toBe("gradient");
    expect(mode.colorExpression[1]).toEqual(["==", ["get", "gradient_percent", ["get", "material_values"]], null]);
  });

  it("改善計画T440: 境界値が2個(3段階)しか無い場合でもクラッシュせず、その数に応じたラベル・色を生成する", () => {
    const axis: CatalogAxis = {
      ...gradientAxis,
      axis_id: "gradient_test",
      map_value_thresholds: [0, 5],
    };
    const mode = routeColorableModeFromAxis(axis);
    expect(mode.legend.map((e) => e.key)).toEqual(["step-0", "step-1", "step-2", "nodata"]);
    expect(mode.legend.map((e) => e.label)).toEqual(["0%未満", "0〜5%", "5%以上", "データなし"]);
  });

  it('windはmap_value_kind==="difficulty"のため難易度経路を使う（axis_difficulties経由）', () => {
    expect(windAxis.map_value_kind).toBe("difficulty");
    const wind = routeColorableModeFromAxis(windAxis);
    expect(wind.id).toBe("wind");
    expect(wind.label).toBe("風の影響");
    expect(wind.colorExpression[1]).toEqual(["==", ["get", "wind", ["get", "axis_difficulties"]], null]);
  });

  it("surface_q（shape.kind==='categorical'）も通常の絶対値差難易度経路を使い、ラベルは他の動的モードと同じ汎用形式になる（roadという専用名は無い）", () => {
    expect(surfaceQAxis.shape?.kind).toBe("categorical");
    const surfaceQ = routeColorableModeFromAxis(surfaceQAxis);
    expect(surfaceQ.id).toBe("surface_q");
    expect(surfaceQ.label).toBe(`${surfaceQAxis.label}の影響`);
    expect(surfaceQ.colorExpression[1]).toEqual(["==", ["get", "surface_q", ["get", "axis_difficulties"]], null]);
  });

  it("interpolateColorsは境界値の個数に関わらずcolorLow→colorHighの間をcount色生成する（固定色配列を持たない）", () => {
    expect(interpolateColors("#16a34a", "#dc2626", 1)).toEqual(["#16a34a"]);
    const three = interpolateColors("#16a34a", "#dc2626", 3);
    expect(three).toHaveLength(3);
    expect(three[0]).toBe("#16a34a");
    expect(three[2]).toBe("#dc2626");
    const five = interpolateColors("#0284c7", "#dc2626", 5);
    expect(five).toHaveLength(5);
    expect(new Set(five).size).toBe(5); // 全段階が異なる色になる
  });

  it("軸がカタログから消える（軸スタジオでunpublish）と、対応するモードも一覧から消える", () => {
    const [dropped, ...rest] = CATALOG_AXES;
    const modes = routeStyleModesFromCatalogAxes(rest);

    expect(modes.map((m) => m.id)).toEqual([...rest.map((axis) => axis.axis_id), "difficulty", "none"]);
    expect(modes.some((m) => m.id === dropped.axis_id)).toBe(false);
  });

  it("改善計画T440: difficultyはどの軸にも対応しないため、軸が0件でも一覧から消えない", () => {
    const modes = routeStyleModesFromCatalogAxes([]);
    expect(modes.map((m) => m.id)).toEqual(["difficulty", "none"]);
  });

  // ルート後の色分けは`axis_difficulties`（0〜100）を塗る。境界がその外に出る軸は、
  // ルート線が全区間同一バンドへ落ち、凡例に到達しない境界が並ぶ（利用者からは
  // 「ルートを生成した瞬間に色分けが壊れる」という形で見える）。軸idを名指しせず、
  // **母集団は合成入力**。公開軸はDBが持つため、ここでは変換が不変条件を保つことだけを
  // 見る。実際の公開軸がこの不変条件を満たすかは、公開時にbackendが検証すべきもの。
  it("map_value_kind=difficultyの軸は、ルート後の色分けの境界がすべて0〜100に収まる", () => {
    const offenders: string[] = [];
    for (const axis of CATALOG_AXES) {
      if ((axis.map_value_kind ?? "difficulty") !== "difficulty") continue;
      const boundaries = steppedBoundariesOf(routeColorableModeFromAxis(axis));
      const outOfRange = boundaries.filter((b) => b < 0 || b > 100);
      if (outOfRange.length > 0) offenders.push(`${axis.axis_id}: ${outOfRange.join(", ")}`);
    }
    expect(offenders).toEqual([]);
  });

  // 値域チェックだけでは足りない。材料スケールの境界が偶然0〜100に収まる軸（停止密度の
  // 回/kmなど）は、値域内のまま「難易度100点満点に対して12点で最上位」という物差しとして
  // 読まれ、全区間が最上位バンドへ落ちる。ramp軸の`display.thresholds`は材料の重み付き和の
  // スケールなので、ルート後の境界がその生値と一致していれば変換されていない証拠になる。
  it("ramp軸のdifficulty境界に、材料スケールの生値がそのまま使われていない", () => {
    const offenders: string[] = [];
    for (const axis of CATALOG_AXES) {
      if (axis.display?.kind !== "ramp") continue;
      if ((axis.map_value_kind ?? "difficulty") !== "difficulty") continue;
      // 分類の軸（`categorical`）は自動導出のしきい値が初めからスコアと同じスケールで、
      // 写す対象ではない（`domain/dynamic_way_values.py: map_value_thresholds`）。
      // 一致していても「変換されていない証拠」にならないため、この検査の対象外。
      if (axis.shape?.kind !== "breakpoint_linear") continue;
      const materialScale = axis.display.thresholds ?? [];
      if (materialScale.length === 0) continue;
      const routeBoundaries = steppedBoundariesOf(routeColorableModeFromAxis(axis));
      if (routeBoundaries.length === materialScale.length && routeBoundaries.every((b, i) => b === materialScale[i])) {
        offenders.push(`${axis.axis_id}: ${routeBoundaries.join(", ")}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  // ルート前の凡例（dedicatedWayValueLegend）だけが体感ラベルを出し、生成すると数値だけに
  // なっていた。ラベルが出ないのは「地図が塗る値へ境界を写したとき、軸の折れ線が飽和する
  // 範囲の境界が同じ値へ潰れて段階が減った」軸に限られる——その軸へラベルをずらして添えると
  // 最上位の段階が実際より狭い範囲を指す嘘になるため、数値だけにしている。軸idを名指しせず、
  // 「畳まれたか」という性質で期待を書く（較正で飽和が解ければラベルが出る側へ移る）。
  it("体感ラベルがルート後の凡例に出ないのは、写像で段階が畳まれた軸だけ", () => {
    const checked: string[] = [];
    for (const axis of CATALOG_AXES) {
      const labels = axis.display_band_labels_override;
      if (!labels || labels.length === 0) continue;
      const collapsed = (axis.map_value_thresholds?.length ?? 0) < (axis.display_thresholds_override?.length ?? 0);
      const legend = routeColorableModeFromAxis(axis).legend;
      const showsLabels = legend.some((entry) => entry.label.startsWith(labels[0]));
      expect(showsLabels, `${axis.axis_id}（畳まれた=${collapsed}）`).toBe(!collapsed);
      checked.push(axis.axis_id);
    }
    expect(checked.length).toBeGreaterThan(0);
  });

  // 本題。ルート確定前の全道路の塗りと、確定後のルート線は**同じ段**で塗る。段の識別子は
  // 前後で同じ保存先（`page.tsx: hiddenLegendKeysByMode[軸id]`）へ書かれるため、綴りか
  // 段数のどちらかがずれると、前に隠した段が生成後に別の段へ化けるか黙って戻る。
  //
  // 母集団は軸カタログから導く——ここに軸idを並べると、軸スタジオで公開を増やしたときに
  // このテストだけが古くなる。
});

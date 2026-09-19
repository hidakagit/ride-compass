// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import * as debugLogModule from "@/lib/debugLog";
import { buildLegendFilterExpression } from "./legendFilter";
import {
  DEFAULT_ROUTE_STYLE_MODE_ID,
  ROUTE_STYLE_MODES,
  getRouteStyleMode,
  isRouteStyleModeId,
  routeColorableModeFromAxis,
  routeStyleModesFromCatalogAxes,
} from "./routeStyleModes";
import { buildAxisRampLegend, rampAxesFromCatalogAxes, type CatalogAxis } from "./axisLayers";
import { interpolateColors } from "./valueScale";
import axisCatalog from "@/types/generated/axis-catalog.json";

const AXES = axisCatalog.axes as CatalogAxis[];

/** 段階色式（`["case", noData, COLOR_NO_DATA, ["step", value, c0, b0, c1, …]]`）が
 * 実際に色を切り替える境界値。宣言ではなく組み立て結果から読むため、境界が式へ渡る
 * 途中で変換されていればその後の値が見える。 */
function steppedBoundariesOf(mode: { colorExpression: unknown[] }): number[] {
  const step = mode.colorExpression.find((part): part is unknown[] => Array.isArray(part) && part[0] === "step");
  if (!step) return [];
  return step.slice(3).filter((part): part is number => typeof part === "number");
}
const gradientAxis = AXES.find((a) => a.axis_id === "gradient")!;
const windAxis = AXES.find((a) => a.axis_id === "wind")!;
const surfaceQAxis = AXES.find((a) => a.axis_id === "surface_q")!;

describe("routeStyleModes", () => {
  // 軸idを名指しせずカタログ順をそのまま期待するのは、公開軸の集合が軸スタジオ（DB）で
  // 決まり生成物の再取り込みで変わるため（GUI作成軸のidは固定値ですらない）。
  it("公開軸すべて（カタログ順）+ difficulty（総合難易度）+ none（レンズなし）を定義する", () => {
    expect(ROUTE_STYLE_MODES.map((m) => m.id)).toEqual([...AXES.map((axis) => axis.axis_id), "difficulty", "none"]);
    expect(DEFAULT_ROUTE_STYLE_MODE_ID).toBe("difficulty");
  });

  it("各モードは凡例と色式を持ち、凡例の色・キーに重複がなく、データなしカテゴリを含む", () => {
    for (const mode of ROUTE_STYLE_MODES) {
      if (mode.id === "none") continue; // レンズなしは凡例を持たない単色モード
      expect(mode.colorExpression.length).toBeGreaterThan(0);
      const colors = mode.legend.map((entry) => entry.color);
      expect(new Set(colors).size).toBe(colors.length);
      const keys = mode.legend.map((entry) => entry.key);
      expect(new Set(keys).size).toBe(keys.length);
      expect(keys).toContain("nodata");
    }
  });

  it("データ欠落（プロパティnull）はグレーへ倒してからstep式で色分けする（to-numberのnull→0変換対策）", () => {
    const wind = getRouteStyleMode(ROUTE_STYLE_MODES, "wind");
    expect(wind.colorExpression[0]).toBe("case");
    expect(wind.colorExpression[1]).toEqual(["==", ["get", "wind", ["get", "axis_difficulties"]], null]);
    expect(wind.colorExpression[2]).toBe("#9ca3af");
    expect((wind.colorExpression[3] as unknown[])[0]).toBe("step");

    const gradient = getRouteStyleMode(ROUTE_STYLE_MODES, "gradient");
    expect(gradient.colorExpression[1]).toEqual(["==", ["get", "gradient_percent", ["get", "material_values"]], null]);
  });

  // 改善計画T466: id未検出時のmodes[0]無警告フォールバックへ警告ログを追加した回帰テスト。
  it("指定idが見つからない場合はmodes[0]へフォールバックしつつ警告を出す", () => {
    const debugLogSpy = vi.spyOn(debugLogModule, "debugLog").mockImplementation(() => {});

    const fallback = getRouteStyleMode(ROUTE_STYLE_MODES, "not-a-real-mode-id" as never);

    expect(fallback.id).toBe(ROUTE_STYLE_MODES[0].id);
    expect(debugLogSpy).toHaveBeenCalledWith(
      "map:route-style-mode",
      expect.stringContaining("not-a-real-mode-id"),
      expect.objectContaining({ requestedId: "not-a-real-mode-id" }),
      "warn",
    );

    debugLogSpy.mockRestore();
  });

  it("指定idが見つかった場合は警告を出さない", () => {
    const debugLogSpy = vi.spyOn(debugLogModule, "debugLog").mockImplementation(() => {});

    getRouteStyleMode(ROUTE_STYLE_MODES, "wind");

    expect(debugLogSpy).not.toHaveBeenCalled();
    debugLogSpy.mockRestore();
  });

  it('gradient(map_value_kind==="signed_material")はgradient_percentを符号付きのまま直接読む——軸idのハードコード分岐ではなくbackendの宣言で判定する', () => {
    expect(gradientAxis.map_value_kind).toBe("signed_material");
    const mode = routeColorableModeFromAxis(gradientAxis);
    expect(mode.id).toBe("gradient");
    expect(mode.colorExpression[1]).toEqual(["==", ["get", "gradient_percent", ["get", "material_values"]], null]);
  });

  it("改善計画T440: gradientのしきい値はカタログのmap_value_thresholds由来で、段階数はその長さ+1になる（固定5カテゴリを仮定しない）", () => {
    expect(gradientAxis.map_value_thresholds).toEqual([-2, 2, 6, 10]);
    const gradient = getRouteStyleMode(ROUTE_STYLE_MODES, "gradient");
    // データなし込みで4境界値+1段階+nodata = 6件
    expect(gradient.legend).toHaveLength(6);
    expect(gradient.legend.map((e) => e.label)).toEqual([
      "-2%未満",
      "-2〜2%",
      "2〜6%",
      "6〜10%",
      "10%以上",
      "データなし",
    ]);
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

  it("凡例タップのフィルタが風モードの各カテゴリで機能する（隣接カテゴリと境界が重ならない）", () => {
    // T599: 本番の風軸のしきい値が[20,40,60,80]（5段階）へ較正された。
    const wind = getRouteStyleMode(ROUTE_STYLE_MODES, "wind");
    const middle = wind.legend[1];
    expect(middle.filter).toEqual([
      "all",
      ["!=", ["get", "wind", ["get", "axis_difficulties"]], null],
      [">=", ["to-number", ["get", "wind", ["get", "axis_difficulties"]]], 20],
      ["<", ["to-number", ["get", "wind", ["get", "axis_difficulties"]]], 40],
    ]);
    expect(buildLegendFilterExpression(wind.legend, [middle.key])).toEqual(["all", ["!", middle.filter]]);
  });

  it("総合難易度モードはdifficulty(0-100絶対基準)を色分けし、レンズなしは凡例を持たない単色になる", () => {
    const difficulty = getRouteStyleMode(ROUTE_STYLE_MODES, "difficulty");
    expect(difficulty.colorExpression[1]).toEqual(["==", ["get", "difficulty"], null]);
    const none = getRouteStyleMode(ROUTE_STYLE_MODES, "none");
    expect(none.legend).toEqual([]);
    expect(none.colorExpression[0]).toBe("to-color");
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

  it("改善計画T440/T549: gradient軸が軸カタログから消える（軸スタジオでunpublish）と、対応するモードも一覧から消える", () => {
    const axesWithoutGradient = AXES.filter((axis) => axis.axis_id !== "gradient");
    const modes = routeStyleModesFromCatalogAxes(axesWithoutGradient);
    expect(modes.map((m) => m.id)).toEqual([...axesWithoutGradient.map((axis) => axis.axis_id), "difficulty", "none"]);
  });

  it("改善計画T440/T549: surface_q軸が軸カタログから消えると、対応するモードも一覧から消える", () => {
    const axesWithoutSurfaceQ = AXES.filter((axis) => axis.axis_id !== "surface_q");
    const modes = routeStyleModesFromCatalogAxes(axesWithoutSurfaceQ);
    expect(modes.map((m) => m.id)).toEqual([...axesWithoutSurfaceQ.map((axis) => axis.axis_id), "difficulty", "none"]);
  });

  it("改善計画T440: difficultyはどの軸にも対応しないため、軸が0件でも一覧から消えない", () => {
    const modes = routeStyleModesFromCatalogAxes([]);
    expect(modes.map((m) => m.id)).toEqual(["difficulty", "none"]);
  });

  // ルート後の色分けは`axis_difficulties`（0〜100）を塗る。境界がその外に出る軸は、
  // ルート線が全区間同一バンドへ落ち、凡例に到達しない境界が並ぶ（利用者からは
  // 「ルートを生成した瞬間に色分けが壊れる」という形で見える）。軸idを名指しせず、
  // 公開軸すべてを母集団にして不変条件そのものを検証する。
  it("map_value_kind=difficultyの軸は、ルート後の色分けの境界がすべて0〜100に収まる", () => {
    const offenders: string[] = [];
    for (const axis of AXES) {
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
    for (const axis of AXES) {
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
    for (const axis of AXES) {
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

  it("体感ラベルを持つ軸の凡例は「ラベル（数値レンジ）」の形で、ルート前と同じ表記になる", () => {
    const wind = getRouteStyleMode(ROUTE_STYLE_MODES, "wind");
    const labels = windAxis.display_band_labels_override!;
    const boundaries = windAxis.map_value_thresholds!;
    const unit = windAxis.map_value_unit ?? "";
    // **先頭帯だけを見ない**。表記がずれるのは端（最上位帯の「以上／超」）なので、
    // 先頭だけ比べると本題を外す。データなしの受け皿は数値レンジを持たないため除く。
    const ranges = [
      `${boundaries[0]}${unit}未満`,
      ...boundaries.slice(1).map((b, i) => `${boundaries[i]}〜${b}${unit}`),
      `${boundaries[boundaries.length - 1]}${unit}以上`,
    ];

    expect(wind.legend.filter((e) => !e.isFallback).map((e) => e.label)).toEqual(
      ranges.map((range, i) => `${labels[i]}（${range}）`),
    );
  });

  // 本題。ルート確定前の全道路の塗りと、確定後のルート線は**同じ段**で塗る。段の識別子は
  // 前後で同じ保存先（`page.tsx: hiddenLegendKeysByMode[軸id]`）へ書かれるため、綴りか
  // 段数のどちらかがずれると、前に隠した段が生成後に別の段へ化けるか黙って戻る。
  //
  // 母集団は軸カタログから導く——ここに軸idを並べると、軸スタジオで公開を増やしたときに
  // このテストだけが古くなる。
  it("公開軸の凡例キーは、ルート確定の前後で一致する", () => {
    const rampAxes = rampAxesFromCatalogAxes(AXES);
    expect(rampAxes.length).toBeGreaterThan(0);

    // 比べるのは**数値の段**だけ。「データなし」の受け皿は量の段ではなく量の不在で、
    // ルート前は値を持たない道が在りうる軸にしか出ない（出ない軸に空の行を足すと、
    // 該当が1本も無い凡例が並ぶ）。受け皿どうしの綴りは下の別テストで固定する。
    const bandKeys = (legend: readonly { key: string; isFallback?: boolean }[]) =>
      legend.filter((entry) => !entry.isFallback).map((entry) => entry.key);

    const mismatches = rampAxes
      .map((axis) => ({
        axisId: axis.axisId,
        before: bandKeys(buildAxisRampLegend(axis)),
        after: bandKeys(getRouteStyleMode(ROUTE_STYLE_MODES, axis.axisId).legend),
      }))
      .filter(({ before, after }) => [...before].sort().join() !== [...after].sort().join())
      .map(({ axisId, before, after }) => `${axisId}: 前=${before.join("/")} 後=${after.join("/")}`);

    expect(mismatches).toEqual([]);
  });

  it("「データなし」の受け皿は、前後で同じ綴りを使う", () => {
    // 綴りが分かれると、ルート前に隠した受け皿がルート生成で戻る（隠した本人には
    // 「一部非表示」の表示だけが残る）。
    const withFallback = rampAxesFromCatalogAxes(AXES)
      .map((axis) => ({
        axisId: axis.axisId,
        before: buildAxisRampLegend(axis).find((entry) => entry.isFallback)?.key,
        after: getRouteStyleMode(ROUTE_STYLE_MODES, axis.axisId).legend.find((entry) => entry.isFallback)?.key,
      }))
      .filter(({ before }) => before !== undefined);

    expect(withFallback.length).toBeGreaterThan(0);
    expect(withFallback.filter(({ before, after }) => before !== after)).toEqual([]);
  });

  it("isRouteStyleModeIdは既知のIDのみtrue（localStorageの壊れた値を弾く）", () => {
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "gradient")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "wind")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "surface_q")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "difficulty")).toBe(true);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "road")).toBe(false);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, "")).toBe(false);
    expect(isRouteStyleModeId(ROUTE_STYLE_MODES, null)).toBe(false);
  });
});

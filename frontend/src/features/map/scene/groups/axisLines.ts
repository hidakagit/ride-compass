/** 評価軸で道を塗る線。軸は管理画面で増減するため、**軸ごとの分岐・定数を持たない**。
 *
 * 値の届き方が2通りある。タイルへ焼き込んだ材料から組み立てるものと、配信された値を
 * feature-state で受け取るもの。**feature-state の値は MapLibre の絞り込みから読めない**
 * ため、凡例で隠した段の落とし方だけが変わる（読めるなら絞り込み、読めないなら透明）。
 *
 * ソースは道路の線と同じ路面タイル。宣言は合成（`composeScene`）が1本へ畳む。
 */
import { mapDisplay } from "@/types/generated/mapDisplay";
import palette from "@/types/generated/palette.json";

import type { MapSceneFeatureStates, MapSceneFeatureStateValue } from "@/features/map/scene/mapScene";
import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "@/features/map/scene/mapSceneGroups";
import type { RampAxis } from "@/lib/mapDisplay/axisLayers";
import { COLOR_UNKNOWN, noDataDashExpression } from "@/features/map/scene/sceneBuilders";
import { LEGEND_NO_DATA_KEY } from "@/lib/mapDisplay/mapColorLegend";

import { ROAD_LINE_SOURCE_ID, ROAD_TRACKS_MAX_SPAN_PX } from "./roadLines";

/** 材料が同時に出ているときの下敷き。**材料の線が全部出たときの帯幅**から決まるので、
 * 線が増えても太くなっても自動で広がる（直書きすると追従しない）。 */
const UNDERLAY_WIDTH_PX = ROAD_TRACKS_MAX_SPAN_PX;
/** 段1つぶん。境界は下限で、判定は`>= 下限`・`< 次の下限`。 */
export type AxisBand = {
  readonly key: string;
  readonly lowerBound: number;
  readonly color: string;
};

type AxisValueSource =
  /** タイルへ焼き込んだ材料から組み立てた値。絞り込みから読める。値の式は欠損を番兵へ
   * 倒してあるため null にならず、評価できない道は `unknown`（真になる式）が示す。
   * 不明という状態を持たない軸は null。 */
  | { readonly kind: "tile"; readonly expression: unknown; readonly unknown: unknown }
  /** 配信された値。feature-state で載せるため、絞り込みからは読めない。値が無い道は null。 */
  | { readonly kind: "delivered"; readonly values: ReadonlyMap<string, number>; readonly loading: boolean };

export type AxisLineState = {
  readonly axes: readonly {
    readonly axisId: string;
    readonly visible: boolean;
    readonly bands: readonly AxisBand[];
    readonly value: AxisValueSource;
    /** 凡例で隠した段の鍵。 */
    readonly hiddenBandKeys: readonly string[];
    /** その軸の材料が同時に出ているか（判定は呼び出し側が持つ）。 */
    readonly underlay: boolean;
  }[];
  readonly sourceLayer: string | null;
};

/** feature-state のキー。軸idから機械的に決める（同じソースへ複数の軸が値を載せるため）。 */
function axisFeatureStateKey(axisId: string): string {
  return `${axisId}Value`;
}

function valueExpression(axisId: string, value: AxisValueSource): unknown {
  return value.kind === "tile" ? value.expression : ["feature-state", axisFeatureStateKey(axisId)];
}

/** その道の値が無い（評価できない）ことを示す式。無いという状態を持たない軸は null。
 * 段の大小比較はこれが偽のときにだけ評価させる——欠損と数値の比較は評価時エラーになり、
 * そのレイヤーだけが黙って描かれなくなる。 */
function missingCondition(axisId: string, value: AxisValueSource): unknown {
  return value.kind === "tile" ? value.unknown : ["==", valueExpression(axisId, value), null];
}

/** 段ごとの色。値が無い道と、まだ来ていない道は別の色にする。値が無い道を段の色で
 * 塗らない——欠損を番兵へ倒した値で段を引くと、評価できない道が最良の段の色になる。
 * 凡例で隠した段は、値の届き方によらず透明にして下の路面の線を見せる（配信値はfeature-stateで載り、
 * 絞り込みからは読めないため、隠し方をこれ1つにそろえる）。 */
function colorExpression(axisId: string, axis: AxisLineState["axes"][number]): unknown {
  const value = valueExpression(axisId, axis.value);
  const loading = axis.value.kind === "delivered" && axis.value.loading;
  const cases: unknown[] = [];
  for (const band of axis.bands) {
    const color = axis.hiddenBandKeys.includes(band.key) ? palette.semantic.hidden : band.color;
    cases.push([">=", value, band.lowerBound], color);
  }
  const missing = missingCondition(axisId, axis.value);
  if (missing === null) return ["case", ...cases, COLOR_UNKNOWN];
  // 取得中の色は「値なし」を隠していても残す——消すと「まだ来ていない」と「隠した」が
  // 区別できなくなる。
  const missingColor = loading
    ? palette.semantic.loading
    : axis.hiddenBandKeys.includes(LEGEND_NO_DATA_KEY)
      ? palette.semantic.hidden
      : COLOR_UNKNOWN;
  return ["case", missing, missingColor, ...cases, COLOR_UNKNOWN];
}

function featureStatesFor(state: AxisLineState): MapSceneFeatureStates {
  const states = new Map<string, ReadonlyMap<string, MapSceneFeatureStateValue>>();
  for (const axis of state.axes) {
    if (axis.value.kind !== "delivered") continue;
    states.set(axisFeatureStateKey(axis.axisId), axis.value.values);
  }
  return states;
}

export const axisLineGroup = declareGroup<AxisLineState>((state) => {
  if (state.sourceLayer === null) return { sources: [], layers: [] };

  const sources: readonly SceneSourceEntry[] = [
    // 宣言そのものは道路の線が持つ。ここは値だけを同じソースへ載せる。
    {
      id: ROAD_LINE_SOURCE_ID,
      spec: { type: "vector" },
      sourceLayer: state.sourceLayer,
      featureStates: featureStatesFor(state),
    },
  ];

  const layers: readonly SceneLayerEntry[] = state.axes.map((axis) => {
    const missing = missingCondition(axis.axisId, axis.value);
    const loading = axis.value.kind === "delivered" && axis.value.loading;
    return {
      role: axis.axisId,
      tier: "lensLine",
      source: ROAD_LINE_SOURCE_ID,
      sourceLayer: state.sourceLayer ?? undefined,
      type: "line",
      paint: {
        "line-color": colorExpression(axis.axisId, axis),
        "line-width": axis.underlay ? UNDERLAY_WIDTH_PX : mapDisplay.road.lineWidthPx,
        // 取得中は薄くしない——薄くすると「まだ来ていない」と「対象外」が区別できない。
        "line-opacity": axis.underlay
          ? mapDisplay.road.unknownOpacity
          : loading || missing === null
            ? mapDisplay.road.knownOpacity
            : ["case", missing, mapDisplay.road.unknownOpacity, mapDisplay.road.knownOpacity],
        // 取得中は破線にしない——まだ来ていないだけで、値が無いとは決まっていない。下敷きは全体を薄く敷くだけ。
        ...(axis.underlay || loading || missing === null ? {} : { "line-dasharray": noDataDashExpression(missing) }),
      },
      visible: axis.visible,
    };
  });

  return { sources, layers };
});

/** hasUnknownFallbackの入力について、その道の値を「不明」とすべきかを返す式。該当する
 * 入力を持たない軸はnull（不明という状態を持たない）。
 *
 * 分類材料（N値文字列、例: highway）は、プロパティの欠損に加えて**値はあるが分類表に
 * 無い**ときも不明に含める。backendの評価（`domain/axis_definitions.py:
 * evaluate_axis_scalar`）は未登録値を評価不能として扱うため、地図だけ「寄与0（最良側）」で
 * 塗ると評価と食い違う。真偽値材料には「未登録値」という状態が無いので欠損だけで判定する。
 *
 * 欠損は`null`のままにせず、同じ型の番兵へ倒してから式へ入れる（文字列なら
 * `"__unknown__"`、数値なら0）。**出力の型が混ざる`case`/`match`を作らない**ための流儀で、
 * 式の評価が落ちてもMapLibreは例外を投げずそのレイヤーだけ黙って描かれなくなる。 */
export function buildAxisRampUnknownExpression(axis: RampAxis): unknown[] | null {
  const checks = axis.tileInputs
    .filter((input) => input.hasUnknownFallback)
    .map((input) => {
      if (input.categories) {
        const knownValuePairs = Object.keys(input.categories).flatMap((key) => [key, false]);
        return ["match", ["coalesce", ["get", input.property], "__unknown__"], ...knownValuePairs, true];
      }
      return ["!", ["has", input.property]];
    });
  if (checks.length === 0) return null;
  return checks.length === 1 ? checks[0] : ["any", ...checks];
}

/** ramp軸の値を組み立てるMapLibre expression。
 *
 * 数値材料はΣ property×weight。重みは軸定義が持ちカタログ経由で届く（フロントに係数を書かない）。
 * プロパティの欠損はタイル側が「0をNULLIFでキー省略」した結果なので0へ倒す。
 * 真偽値材料はMVTの真偽値を比較でしか読めず重み付き和が成り立たないため、
 * ["case", 真偽比較, trueValue, falseValue]で寄与値を直接置く。N値文字列材料・自己変換材料は
 * それぞれ["match", ...]・["interpolate", ...]で寄与値を作る。 */
export function buildAxisRampValueExpression(axis: RampAxis): unknown[] {
  const terms = axis.tileInputs.map((input) => {
    if (input.boolean) {
      const comparison = ["==", ["get", input.property], true];
      return ["case", comparison, input.trueValue ?? 0, input.falseValue ?? 0];
    }
    if (input.categories) {
      const value = [
        "match",
        ["coalesce", ["get", input.property], "__unknown__"],
        ...Object.entries(input.categories).flatMap(([key, score]) => [key, score * input.weight]),
        0,
      ];
      return value;
    }
    if (input.breakpoints) {
      // 欠損はbackendのrequired=False材料と同じく寄与0にする。coalesceで端へ倒すとinterpolateが
      // 端の値（例: -1）を返し、寄与0にならない。
      const interpolated = ["interpolate", ["linear"], ["get", input.property], ...input.breakpoints.flat()];
      const value = input.weight === 1 ? interpolated : ["*", interpolated, input.weight];
      return ["case", ["!", ["has", input.property]], 0, value];
    }
    return ["*", ["coalesce", ["get", input.property], 0], input.weight];
  });
  if (terms.length === 1) return terms[0];
  return ["+", ...terms];
}

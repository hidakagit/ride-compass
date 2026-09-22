/** 評価軸で道を塗る線。軸は管理画面で増減するため、**軸ごとの分岐・定数を持たない**。
 *
 * 値の届き方が2通りある。タイルへ焼き込んだ材料から組み立てるものと、配信された値を
 * feature-state で受け取るもの。**feature-state の値は MapLibre の絞り込みから読めない**
 * ため、凡例で隠した段の落とし方だけが変わる（読めるなら絞り込み、読めないなら透明）。
 *
 * ソースは道路の線と同じ路面タイル。宣言は合成（`composeScene`）が1本へ畳む。
 */
import type { FilterSpecification } from "maplibre-gl";

import type { MapSceneFeatureStates, MapSceneFeatureStateValue } from "../mapScene";
import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";
import { ROAD_LINE_SOURCE_ID } from "./roadLines";

const LINE_WIDTH_PX = 3;
/** 材料が同時に出ているときの下敷き。太く半透明にして、材料の線を上に読ませる。 */
const UNDERLAY_WIDTH_PX = 9;
const UNDERLAY_OPACITY = 0.35;
const KNOWN_OPACITY = 0.9;
/** 値を受け取れなかった道。薄くしないと、値のある道がそこへ埋もれる。 */
const UNKNOWN_OPACITY = 0.35;
const NO_VALUE_COLOR = "#94a3b8";
/** まだ値が来ていない間の色。**隠す指定があっても残す**——「まだ来ていない」と
 * 「隠した」が区別できなくなるため。 */
const LOADING_COLOR = "#cbd5e1";

/** 値を持たない道を受け持つ段の鍵。境界を持たないので、段の一覧には現れない。 */
export const NO_VALUE_BAND_KEY = "nodata";

/** 段1つぶん。境界は下限で、判定は`>= 下限`・`< 次の下限`。 */
export type AxisBand = {
  readonly key: string;
  readonly lowerBound: number;
  readonly color: string;
};

export type AxisValueSource =
  /** タイルへ焼き込んだ材料から組み立てた値。絞り込みから読める。 */
  | { readonly kind: "tile"; readonly expression: unknown }
  /** 配信された値。feature-state で載せるため、絞り込みからは読めない。 */
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
export function axisFeatureStateKey(axisId: string): string {
  return `${axisId}Value`;
}

function valueExpression(axisId: string, value: AxisValueSource): unknown {
  return value.kind === "tile" ? value.expression : ["feature-state", axisFeatureStateKey(axisId)];
}

/** 段ごとの色。値が無い道と、まだ来ていない道は別の色にする。 */
function colorExpression(axisId: string, axis: AxisLineState["axes"][number]): unknown {
  const value = valueExpression(axisId, axis.value);
  const loading = axis.value.kind === "delivered" && axis.value.loading;
  const cases: unknown[] = [];
  for (const band of axis.bands) {
    const hidden = axis.hiddenBandKeys.includes(band.key);
    // 読めない値の段は、落とすのではなく透明にする（下の路面の線を見せる）。
    const color = hidden && axis.value.kind === "delivered" ? "rgba(0,0,0,0)" : band.color;
    cases.push([">=", value, band.lowerBound], color);
  }
  return ["case", ["==", value, null], loading ? LOADING_COLOR : NO_VALUE_COLOR, ...cases.flat(), NO_VALUE_COLOR];
}

/** 絞り込みから読める値のときだけ、隠した段を落とす。 */
function bandFilter(axis: AxisLineState["axes"][number], axisId: string): FilterSpecification | undefined {
  if (axis.value.kind !== "tile" || axis.hiddenBandKeys.length === 0) return undefined;
  const value = valueExpression(axisId, axis.value);
  const hidden = axis.bands.filter((band) => axis.hiddenBandKeys.includes(band.key));
  const clauses: unknown[] = hidden.map((band) => ["!", [">=", value, band.lowerBound]]);
  // 値を持たない道は、段を隠しただけでは落ちない（大小比較が成り立たないため）。
  // 「値なし」の段を隠したときだけ落とす。
  if (axis.hiddenBandKeys.includes(NO_VALUE_BAND_KEY)) clauses.push(["!=", value, null]);
  if (clauses.length === 0) return undefined;
  return ["all", ...clauses] as unknown as FilterSpecification;
}

function featureStatesFor(state: AxisLineState): MapSceneFeatureStates {
  const states = new Map<string, ReadonlyMap<string, MapSceneFeatureStateValue>>();
  for (const axis of state.axes) {
    if (axis.value.kind !== "delivered") continue;
    states.set(axisFeatureStateKey(axis.axisId), axis.value.values);
  }
  return states;
}

export const axisLineGroup = declareGroup<AxisLineState>("axis", (state) => {
  if (state.sourceLayer === null) return { sources: [], layers: [] };

  const sources: readonly SceneSourceEntry[] = [
    // 宣言そのものは道路の線が持つ。ここは値だけを同じソースへ載せる。
    { id: ROAD_LINE_SOURCE_ID, spec: { type: "vector" }, sourceLayer: state.sourceLayer, featureStates: featureStatesFor(state) },
  ];

  const layers: readonly SceneLayerEntry[] = state.axes.map((axis) => ({
    role: axis.axisId,
    tier: "lensLine",
    source: ROAD_LINE_SOURCE_ID,
    sourceLayer: state.sourceLayer ?? undefined,
    type: "line",
    paint: {
      "line-color": colorExpression(axis.axisId, axis),
      "line-width": axis.underlay ? UNDERLAY_WIDTH_PX : LINE_WIDTH_PX,
      // 取得中は薄くしない——薄くすると「まだ来ていない」と「対象外」が区別できない。
      "line-opacity": axis.underlay
        ? UNDERLAY_OPACITY
        : axis.value.kind === "delivered" && axis.value.loading
          ? KNOWN_OPACITY
          : ["case", ["==", valueExpression(axis.axisId, axis.value), null], UNKNOWN_OPACITY, KNOWN_OPACITY],
    },
    visible: axis.visible,
    ...(bandFilter(axis, axis.axisId) === undefined ? {} : { filter: bandFilter(axis, axis.axisId) }),
  }));

  return { sources, layers };
});

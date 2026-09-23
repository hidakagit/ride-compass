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
import type { FilterSpecification } from "maplibre-gl";

import type { MapSceneFeatureStates, MapSceneFeatureStateValue } from "../mapScene";
import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";
import { COLOR_UNKNOWN } from "@/components/Map/axisLayers";
import { LEGEND_NO_DATA_KEY } from "@/components/Map/mapColorLegend";

import { ROAD_LINE_SOURCE_ID, ROAD_TRACKS } from "./roadLines";

/** 材料が同時に出ているときの下敷き。**材料の線が全部出たときの帯幅**から決まるので、
 * トラックが増えれば自動で広がる（直書きすると追従しない）。 */
const UNDERLAY_WIDTH_PX = (ROAD_TRACKS.length - 1) * mapDisplay.road.trackOffsetStepPx + mapDisplay.road.lineWidthPx;
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
 * 塗らない——欠損を番兵へ倒した値で段を引くと、評価できない道が最良の段の色になる。 */
function colorExpression(axisId: string, axis: AxisLineState["axes"][number]): unknown {
  const value = valueExpression(axisId, axis.value);
  const delivered = axis.value.kind === "delivered";
  const loading = axis.value.kind === "delivered" && axis.value.loading;
  const cases: unknown[] = [];
  for (const band of axis.bands) {
    const hidden = axis.hiddenBandKeys.includes(band.key);
    // 読めない値の段は、落とすのではなく透明にする（下の路面の線を見せる）。
    const color = hidden && delivered ? palette.semantic.hidden : band.color;
    cases.push([">=", value, band.lowerBound], color);
  }
  const missing = missingCondition(axisId, axis.value);
  if (missing === null) return ["case", ...cases, COLOR_UNKNOWN];
  // 取得中の色は「値なし」を隠していても残す——消すと「まだ来ていない」と「隠した」が
  // 区別できなくなる。
  const missingColor = loading
    ? palette.semantic.loading
    : delivered && axis.hiddenBandKeys.includes(LEGEND_NO_DATA_KEY)
      ? palette.semantic.hidden
      : COLOR_UNKNOWN;
  return ["case", missing, missingColor, ...cases, COLOR_UNKNOWN];
}

/** 絞り込みから読める値のときだけ、隠した段を落とす。段は下限だけを持つので、上限は
 * 1つ上の段の下限から決める（下限だけで落とすと、それより上の段まで一緒に消える）。 */
function bandFilter(axis: AxisLineState["axes"][number], axisId: string): FilterSpecification | undefined {
  if (axis.value.kind !== "tile" || axis.hiddenBandKeys.length === 0) return undefined;
  const value = valueExpression(axisId, axis.value);
  const missing = missingCondition(axisId, axis.value);
  const ascending = [...axis.bands].sort((a, b) => a.lowerBound - b.lowerBound);
  const clauses: unknown[] = [];
  ascending.forEach((band, index) => {
    if (!axis.hiddenBandKeys.includes(band.key)) return;
    const upper = ascending[index + 1]?.lowerBound;
    const inBand = [
      "all",
      ...(Number.isFinite(band.lowerBound) ? [[">=", value, band.lowerBound]] : []),
      ...(upper === undefined ? [] : [["<", value, upper]]),
    ];
    clauses.push(missing === null ? ["!", inBand] : ["any", missing, ["!", inBand]]);
  });
  // 値を持たない道は段に属さないため、「値なし」の段を隠したときだけ落とす。
  if (missing !== null && axis.hiddenBandKeys.includes(LEGEND_NO_DATA_KEY)) clauses.push(["!", missing]);
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
    const filter = bandFilter(axis, axis.axisId);
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
          : (axis.value.kind === "delivered" && axis.value.loading) || missing === null
            ? mapDisplay.road.knownOpacity
            : ["case", missing, mapDisplay.road.unknownOpacity, mapDisplay.road.knownOpacity],
      },
      visible: axis.visible,
      ...(filter === undefined ? {} : { filter }),
    };
  });

  return { sources, layers };
});

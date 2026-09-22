/** 点で示すもの（停止要因POI・補給休憩POI・事故地点）。
 *
 * **何を点で描くかはここが宣言する**。点になりうる属性は源泉（`primary-attributes.json`の
 * `geometry="point"`）が持ち、そのうちどれを出すかは画面の判断——分類と色を宣言したものが
 * 出る（交差点は道路網を見れば分かるので出さない）。
 *
 * 停止要因と補給は**同じソース・同じsource-layerを共有し、種別の集合で分ける**——
 * 分ける条件を持たないと互いの点が混ざる。その集合は源泉（`poi-kinds.json`）から取る
 * ので、backendが種別を増やしたときに地図から消えることはない（色だけが未分類になる）。
 * 事故は配信の系統が違うため別のソース。
 *
 * **タイルの世代が届くまでソースを作らない**。先に作ると、世代の違う中身がブラウザの
 * キャッシュへ載って以後ずっと残る。
 */
import palette from "@/types/generated/palette.json";
import type { FilterSpecification } from "maplibre-gl";

import { primaryAttributes } from "@/types/generated/primaryAttributes";

import { COLOR_UNKNOWN } from "@/components/Map/axisLayers";

import { declareGroup, type LegendRow, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";

const RADIUS_PX = 4;
/** 死亡事故だけは大きく出す（重大度は色ではなく大きさで示し、当事者の色と取り合わない）。 */
const FATAL_RADIUS_PX = 6;
const NON_FATAL_RADIUS_PX = 3;
const STROKE_WIDTH_PX = 1;
const STROKE_COLOR = palette.semantic.mark_stroke;
const OPACITY = 0.9;
const ACCIDENT_OPACITY = 0.75;

/** 点で描くもの。**源泉が「点の幾何を持ち、表示の定義がある」と言ったものが出る。**
 * 軸・束ね方・行の名前・色・どのタイルに載るかは、すべて源泉が決める。 */
export const POINT_LAYERS = primaryAttributes.filter(
  (attr): attr is typeof attr & { tile_kind: string } =>
    attr.geometry === "point" && attr.display_axes.length > 0 && attr.tile_kind !== null,
);

type PointLayer = (typeof POINT_LAYERS)[number];
export type PointAxis = PointLayer["display_axes"][number];

/** 常に効く絞り込み。停止要因と補給は同じタイル・同じsource-layerを分け合うので、
 * 自分の行に属する値だけを通す（持たないと互いの点が混ざる）。 */
function baseFilter(layer: PointLayer): FilterSpecification | undefined {
  if (layer.tile_kind !== "poi") return undefined;
  const axis = layer.display_axes[0];
  const values: (string | boolean)[] = axis.categories.flatMap((category) => [...category.values]);
  return ["in", ["get", axis.property], ["literal", values]] as unknown as FilterSpecification;
}

export type PointState = {
  /** タイルの配信先。**世代が届くまでは null**——その間は何も作らない。 */
  readonly tiles: {
    readonly poi: readonly string[];
    readonly accident: readonly string[];
    readonly poiSourceLayer: string;
    readonly accidentSourceLayer: string;
    readonly minZoom: number;
    readonly maxZoom: number;
  } | null;
  /** 役割ごとの表示ON/OFF。 */
  readonly visible: Readonly<Record<string, boolean>>;
  /** 軸の鍵ごとの、凡例で隠した行の鍵。 */
  readonly hiddenKeys: Readonly<Record<string, readonly string[]>>;
};

/** ソースのidは系統の名前から決まる（対応表を持たない）。 */
export function pointSourceId(tileKind: string): string {
  return `point-${tileKind}`;
}

/** 押したときに拾う対象。**どの点も共通の`point`を名乗る**ので、点を1枚足しても
 * 拾う側の判定は変わらない。 */
export const POINT_HIT_TARGET = "point";

/** 軸の絞り込みの鍵。役割をまたいで同じ軸名を使えるようにする。 */
export function pointAxisKey(layer: PointLayer, axis: PointAxis): string {
  return `${layer.attr_id}:${axis.key}`;
}

function valueOf(axis: PointAxis): unknown {
  return ["get", axis.property];
}

/** 分類ごとの色。隠した行も含めて作る——隠しても残った分類の色が動かないようにする。 */
function colorExpression(layer: PointLayer): unknown {
  const axis = layer.display_axes[0];
  // 行が1つも無いときに`case`を出すと、対を持たない式になって地図が受け付けない。
  if (axis === undefined) return COLOR_UNKNOWN;
  const cases = axis.categories.flatMap((category) => [
    ["in", valueOf(axis), ["literal", [...category.values]]],
    category.color,
  ]);
  return ["case", ...cases, COLOR_UNKNOWN];
}

/** 通す分類だけを残す絞り込み。軸が複数あるときはすべてANDで効く。 */
function layerFilter(layer: PointLayer, hiddenKeys: PointState["hiddenKeys"]): FilterSpecification | undefined {
  const clauses: unknown[] = [];
  const base = baseFilter(layer);
  if (base !== undefined) clauses.push(base);
  for (const axis of layer.display_axes) {
    const hidden = hiddenKeys[pointAxisKey(layer, axis)] ?? [];
    if (hidden.length === 0) continue;
    const values = axis.categories.filter((c) => hidden.includes(c.key)).flatMap((c) => [...c.values]);
    if (values.length === 0) continue;
    clauses.push(["!", ["in", valueOf(axis), ["literal", values]]]);
  }
  if (clauses.length === 0) return undefined;
  if (clauses.length === 1) return clauses[0] as FilterSpecification;
  return ["all", ...clauses] as unknown as FilterSpecification;
}

/** 重大度の軸を持つ点だけ、大きさでも重大度を示す。 */
function radiusExpression(layer: PointLayer): unknown {
  const severity = layer.display_axes.find((axis) => axis.key === "severity");
  if (severity === undefined) return RADIUS_PX;
  return ["case", ["==", ["get", severity.property], true], FATAL_RADIUS_PX, NON_FATAL_RADIUS_PX];
}

export const pointGroup = declareGroup<PointState>("point", (state) => {
  if (state.tiles === null) return { sources: [], layers: [] };
  const tiles = state.tiles;

  const sources: readonly SceneSourceEntry[] = [
    {
      id: pointSourceId("poi"),
      spec: { type: "vector", minzoom: tiles.minZoom, maxzoom: tiles.maxZoom },
      sourceLayer: tiles.poiSourceLayer,
      tiles: tiles.poi,
    },
    {
      id: pointSourceId("accident"),
      spec: { type: "vector", minzoom: tiles.minZoom, maxzoom: tiles.maxZoom },
      sourceLayer: tiles.accidentSourceLayer,
      tiles: tiles.accident,
    },
  ];

  const layers: readonly SceneLayerEntry[] = POINT_LAYERS.map((layer) => ({
    role: layer.attr_id,
    tier: "point",
    source: pointSourceId(layer.tile_kind),
    sourceLayer: layer.tile_kind === "accident" ? tiles.accidentSourceLayer : tiles.poiSourceLayer,
    type: "circle",
    paint: {
      "circle-color": colorExpression(layer),
      "circle-radius": radiusExpression(layer),
      "circle-stroke-width": STROKE_WIDTH_PX,
      "circle-stroke-color": STROKE_COLOR,
      "circle-opacity": layer.tile_kind === "accident" ? ACCIDENT_OPACITY : OPACITY,
    },
    visible: state.visible[layer.attr_id] === true,
    hitTargets: [POINT_HIT_TARGET, `${POINT_HIT_TARGET}:${layer.attr_id}`],
    ...(layerFilter(layer, state.hiddenKeys) === undefined
      ? {}
      : { filter: layerFilter(layer, state.hiddenKeys) }),
  }));

  return { sources, layers };
});

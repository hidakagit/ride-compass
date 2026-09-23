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
import { sceneSourceId, type SceneSourceId } from "../sceneBuilders";
import { mapDisplay } from "@/types/generated/mapDisplay";
import palette from "@/types/generated/palette.json";
import type { FilterSpecification } from "maplibre-gl";

import { primaryAttributes } from "@/types/generated/primaryAttributes";

import { COLOR_UNKNOWN } from "@/components/Map/axisLayers";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";

const POINT = mapDisplay.point;

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
export function pointSourceId(tileKind: string): SceneSourceId {
  return sceneSourceId(`point-${tileKind}`);
}

/** 押したときに拾う対象。**どの点も共通の`point`を名乗る**ので、点を1枚足しても
 * 拾う側の判定は変わらない。 */
const POINT_HIT_TARGET = "point";

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

/** 大きさで示す軸。色は先頭の軸が持つので、重大度は大きさだけで示す（色を取り合わない）。 */
function sizeAxis(layer: PointLayer): PointAxis | undefined {
  return layer.display_axes.find((axis) => axis.key === "severity");
}

/** 行が地図に描かれる半径。**凡例の見本も同じ関数を読む**——凡例が別に大きさを持つと、
 * 地図と食い違う。大きさの軸でない行は既定の半径。 */
export function pointCategoryRadiusPx(
  layer: PointLayer,
  axis: PointAxis,
  category: PointAxis["categories"][number],
): number {
  if (axis !== sizeAxis(layer)) return POINT.radiusPx;
  return (category.values as readonly (string | boolean)[]).includes(true)
    ? POINT.fatalRadiusPx
    : POINT.nonFatalRadiusPx;
}

function radiusExpression(layer: PointLayer): unknown {
  const axis = sizeAxis(layer);
  if (axis === undefined) return POINT.radiusPx;
  const cases = axis.categories.flatMap((category) => [
    ["in", valueOf(axis), ["literal", [...category.values]]],
    pointCategoryRadiusPx(layer, axis, category),
  ]);
  return ["case", ...cases, POINT.radiusPx];
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
      "circle-stroke-width": POINT.strokeWidthPx,
      "circle-stroke-color": palette.semantic.mark_stroke,
      "circle-opacity": layer.tile_kind === "accident" ? POINT.accidentOpacity : POINT.opacity,
    },
    visible: state.visible[layer.attr_id] === true,
    hitTargets: [POINT_HIT_TARGET, `${POINT_HIT_TARGET}:${layer.attr_id}`],
    ...(layerFilter(layer, state.hiddenKeys) === undefined ? {} : { filter: layerFilter(layer, state.hiddenKeys) }),
  }));

  return { sources, layers };
});

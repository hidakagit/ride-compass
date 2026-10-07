/** 点で示すもの（停止要因POI・補給休憩POI・事故地点）。
 *
 * **何を点で描くかは源泉が決める**。点になりうる属性は源泉（生成物`primaryAttributes.ts`の
 * `geometry="point"`）が持ち、そのうち表示の定義（`display_axes`）を持つものだけが出る
 * （交差点は表示の定義を持たないので出ない）。
 *
 * 点のソースは、配信される点のタイルの一覧（生成物`region-tile-config.json`の`point_layers`）から1つずつ作り、
 * レイヤーは自分の`tile_kind`のソースを読む。**同じタイルを2つ以上のレイヤーが分け合うときは、種別の集合で分ける**
 * ——分ける条件を持たないと互いの点が混ざる。その集合は源泉の表示の行（`display_axes`の値）から
 * 取る。行が種別を取りこぼすと、その種別の点は地図から消える——行と種別の一覧が一致することは
 * backendのテスト（`test_material_catalog.py`）が全種別で確かめる。
 *
 * 点の形も源泉が決める。先頭の軸の行が絵記号（`glyph`）を持つレイヤーは、行の色の角丸四角に絵記号を載せた
 * 記号で描き、持たないレイヤーは丸い点で描く。
 *
 * **タイルの世代が届くまでソースを作らない**。先に作ると、世代の違う中身がブラウザの
 * キャッシュへ載って以後ずっと残る。
 */
import type { PointTileLayer } from "@/features/map/regionApi";
import { sceneSourceId, type SceneSourceId } from "@/features/map/scene/sceneBuilders";
import { mapDisplay } from "@/types/generated/mapDisplay";
import palette from "@/types/generated/palette.json";
import regionTileConfig from "@/types/generated/region-tile-config.json";
import type { FilterSpecification } from "maplibre-gl";

import type { PointGlyph } from "@/lib/mapDisplay/legendFilter";
import { primaryAttributes } from "@/types/generated/primaryAttributes";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "@/features/map/scene/mapSceneGroups";

const POINT = mapDisplay.point;

/** 配信される点のタイルの名前 → source-layer。 */
const POINT_TILE_SOURCE_LAYERS: Readonly<Record<PointTileLayer, string>> = regionTileConfig.point_layers;

function isPointTileLayer(name: string | null): name is PointTileLayer {
  return name !== null && Object.hasOwn(POINT_TILE_SOURCE_LAYERS, name);
}

const POINT_TILE_LAYERS = Object.keys(POINT_TILE_SOURCE_LAYERS).filter(isPointTileLayer);

/** 点のタイルごとの地図のソースとsource-layer。 */
export const POINT_TILE_SOURCES = Object.fromEntries(
  POINT_TILE_LAYERS.map((name) => [
    name,
    { sourceId: sceneSourceId(`point-${name}`), sourceLayer: POINT_TILE_SOURCE_LAYERS[name] },
  ]),
) as Readonly<Record<PointTileLayer, { readonly sourceId: SceneSourceId; readonly sourceLayer: string }>>;

/** 点で描くもの。**源泉が「点の幾何を持ち、表示の定義がある」と言ったものが出る。**
 * 軸・束ね方・行の名前・色・どのタイルに載るかは、すべて源泉が決める。点の属性の`tile_kind`が配信される
 * 点のタイルを指すことは、backendのテスト（`test_point_tile_layers.py`）が確かめる。 */
export const POINT_LAYERS = primaryAttributes.filter(
  (attr): attr is typeof attr & { tile_kind: PointTileLayer } =>
    attr.geometry === "point" && attr.display_axes.length > 0 && isPointTileLayer(attr.tile_kind),
);

type PointLayer = (typeof POINT_LAYERS)[number];
export type PointAxis = PointLayer["display_axes"][number];

/** 常に効く絞り込み。同じタイル・同じsource-layerを2つ以上のレイヤーが分け合うときは、
 * 自分の行に属する値だけを通す（持たないと互いの点が混ざる）。 */
function baseFilter(layer: PointLayer): FilterSpecification | undefined {
  if (POINT_LAYERS.filter((other) => other.tile_kind === layer.tile_kind).length < 2) return undefined;
  const axis = layer.display_axes[0];
  const values: (string | boolean)[] = axis.categories.flatMap((category) => [...category.values]);
  return ["in", ["get", axis.property], ["literal", values]] as unknown as FilterSpecification;
}

export type PointState = {
  /** タイルの配信先。**世代が届くまでは null**——その間は何も作らない。 */
  readonly tiles: {
    readonly urls: Readonly<Record<PointTileLayer, readonly string[]>>;
    readonly minZoom: number;
    readonly maxZoom: number;
  } | null;
  /** 役割ごとの表示ON/OFF。 */
  readonly visible: Readonly<Record<string, boolean>>;
  /** 軸の鍵ごとの、凡例で隠した行の鍵。 */
  readonly hiddenKeys: Readonly<Record<string, readonly string[]>>;
};

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
  if (axis === undefined) return palette.semantic.no_data;
  const cases = axis.categories.flatMap((category) => [
    ["in", valueOf(axis), ["literal", [...category.values]]],
    category.color,
  ]);
  return ["case", ...cases, palette.semantic.no_data];
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

type GlyphCategory = Extract<PointAxis["categories"][number], { glyph: string; color: string }>;

/** 絵記号で描くレイヤーの行。源泉は先頭の軸の行の全部に付けるか、どれにも付けない。 */
function glyphCategories(layer: PointLayer): readonly GlyphCategory[] {
  const categories: readonly PointAxis["categories"][number][] = layer.display_axes[0]?.categories ?? [];
  return categories.filter((category): category is GlyphCategory => "glyph" in category && "color" in category);
}

/** 地図へ登録する絵の名前。**登録側と参照側が同じ1つを使う**（綴りがずれると点が出ない）。 */
function pointIconId(layer: PointLayer, category: GlyphCategory): string {
  return `point-icon:${layer.attr_id}:${category.key}`;
}

/** 絵記号で描く点の絵（名前・下地の色・絵記号）。**出す前に地図へ登録しないと点が描かれない。** */
export const POINT_ICONS: readonly { id: string; color: string; glyph: PointGlyph }[] = POINT_LAYERS.flatMap((layer) =>
  glyphCategories(layer).map((category) => ({
    id: pointIconId(layer, category),
    color: category.color,
    glyph: category.glyph,
  })),
);

function iconImageExpression(layer: PointLayer, categories: readonly GlyphCategory[]): unknown {
  const axis = layer.display_axes[0];
  const cases = categories.flatMap((category) => [
    ["in", valueOf(axis), ["literal", [...category.values]]],
    pointIconId(layer, category),
  ]);
  return ["case", ...cases, ""];
}

/** 大きさで示す軸。源泉が行に半径を付けた軸で、付けるのは点の軸のうち1本だけ。 */
function sizeAxis(layer: PointLayer): PointAxis | undefined {
  return layer.display_axes.find((axis) => axis.categories.some((category) => "radius_px" in category));
}

/** 行が地図に描かれる半径。**凡例の見本も同じ関数を読む**——凡例が別に大きさを持つと、
 * 地図と食い違う。半径を持たない行は既定の半径。 */
export function pointCategoryRadiusPx(category: PointAxis["categories"][number]): number {
  return "radius_px" in category ? category.radius_px : POINT.radiusPx;
}

function radiusExpression(layer: PointLayer): unknown {
  const axis = sizeAxis(layer);
  if (axis === undefined) return POINT.radiusPx;
  const cases = axis.categories.flatMap((category) => [
    ["in", valueOf(axis), ["literal", [...category.values]]],
    pointCategoryRadiusPx(category),
  ]);
  return ["case", ...cases, POINT.radiusPx];
}

export const pointGroup = declareGroup<PointState>((state) => {
  if (state.tiles === null) return { sources: [], layers: [] };
  const tiles = state.tiles;

  const sources: readonly SceneSourceEntry[] = POINT_TILE_LAYERS.map((name) => ({
    id: POINT_TILE_SOURCES[name].sourceId,
    spec: { type: "vector", minzoom: tiles.minZoom, maxzoom: tiles.maxZoom },
    sourceLayer: POINT_TILE_SOURCES[name].sourceLayer,
    tiles: tiles.urls[name],
  }));

  const layers: readonly SceneLayerEntry[] = POINT_LAYERS.map((layer) => {
    const glyphs = glyphCategories(layer);
    const opacity = POINT.opacityByLayer[layer.attr_id];
    const filter = layerFilter(layer, state.hiddenKeys);
    return {
      role: layer.attr_id,
      tier: "point",
      source: POINT_TILE_SOURCES[layer.tile_kind].sourceId,
      sourceLayer: POINT_TILE_SOURCES[layer.tile_kind].sourceLayer,
      ...(glyphs.length === 0
        ? {
            type: "circle" as const,
            paint: {
              "circle-color": colorExpression(layer),
              "circle-radius": radiusExpression(layer),
              "circle-stroke-width": POINT.strokeWidthPx,
              "circle-stroke-color": palette.semantic.mark_stroke,
              "circle-opacity": opacity,
            },
          }
        : {
            type: "symbol" as const,
            paint: { "icon-opacity": opacity },
            // 点を間引かない。丸い点と同じく、重なっても全部描く。
            layout: {
              "icon-image": iconImageExpression(layer, glyphs),
              "icon-allow-overlap": true,
              "icon-ignore-placement": true,
            },
          }),
      visible: state.visible[layer.attr_id] === true,
      hitTargets: [POINT_HIT_TARGET],
      ...(filter === undefined ? {} : { filter }),
    };
  });

  return { sources, layers };
});

/** 画面の状態を地図へ当てる。**ここが唯一の適用の入口**。
 *
 * 状態 → 各家族の入力（`sceneInputsFrom`）→ 望ましい並び（`buildMapScene`）→
 * 差分を当てる（`applyMapScene`）の1本道。作り直し（`redrawAllLayers`）も同じ道を通り、
 * 前回との差分ではなく空から当て直すだけが違う。
 *
 * **再描画で失われる副作用を持つ描画は、必ずここから辿れる位置へ置く。** レイヤーの
 * 追加だけでなく、filter・feature-state・visibilityで持つ表示状態も同じ。辿れないものは
 * `setStyle()`後に作り直されず、押した人の地図から消えたままになる。
 *
 * カメラは動かさない——作り直しは見た目を戻すだけで、表示範囲は利用者のもの。
 */
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";

import type { MapViewProps } from "@/components/Map/MapView";
import {
  COLOR_UNKNOWN,
  axisMapLayerId,
  buildAxisRampValueExpression,
  dedicatedWayValueMapLayerId,
  rampColorForBand,
  type RampAxis,
} from "@/components/Map/axisLayers";
import {
  DEFAULT_DEDICATED_WAY_VALUE_DISPLAY,
  type DedicatedWayValueDisplay,
} from "@/components/Map/dedicatedWayValueLayer";
import type { DynamicWeatherRenderPayload } from "@/components/Map/dynamicWeather";
import { withJmaTileProtocol } from "@/components/Map/jmaTileProtocol";
import { buildLegendFilterExpression } from "@/components/Map/legendFilter";
import { legendBandKey } from "@/components/Map/mapColorLegend";
import { areaLayerAnchor, runWhenStyleReady } from "@/components/Map/mapStyleOps";
import { ROUTE_ARROW_ICON_ID, createRouteArrowIcon } from "@/components/Map/routeArrowIcon";
import { LENS_NEUTRAL_COLOR, getRouteStyleMode } from "@/components/Map/routeStyleModes";
import { bandColorsFor, DEFAULT_DIFFICULTY_BOUNDARIES } from "@/components/Map/valueScale";
import { tileBaseUrl } from "@/lib/tileBaseUrl";
import {
  ROAD_TILE_MAX_ZOOM,
  ROAD_TILE_MIN_ZOOM,
  accidentTileUrl,
  hasTileVersions,
  landcoverTileUrl,
  poiTileUrl,
  roadSurfaceTileUrl,
} from "@/services/regionApi";
import regionTileConfig from "@/types/generated/region-tile-config.json";

/** ベクタタイル内のレイヤー名。源泉が配る値をそのまま使う。 */
const ROAD_TILE_SOURCE_LAYER = regionTileConfig.road_surface.layer_name;
const ACCIDENT_TILE_SOURCE_LAYER = regionTileConfig.accident.layer_name;
const STOP_POI_SOURCE_LAYER = regionTileConfig.poi.stop_poi_layer_name;

import { applyMapScene } from "./applyMapScene";
import { buildMapScene, type SceneInputs } from "./buildScene";
import type { AxisBand, AxisLineState } from "./groups/axisLines";
import type { RoutePath, RouteState } from "./groups/routes";
import { WEATHER_ICONS, type WeatherPayload, type WeatherState } from "./groups/weather";
import { EMPTY_MAP_SCENE, type MapScene } from "./mapScene";

type RedrawAllLayersProps = Pick<
  MapViewProps,
  | "routes"
  | "selectedRouteId"
  | "routeLayerOn"
  | "routeStyleModes"
  | "routeStyleModeId"
  | "hiddenRouteLegendKeys"
  | "spliceStretches"
  | "splicedRoute"
  | "staticLayerVisibility"
  | "dynamicWeather"
  | "dedicatedWayValueVisibility"
  | "axisVisibility"
  | "roadHiddenKeysByMode"
  | "staticLegendHiddenKeysByAxis"
  | "experimentSlots"
  | "dedicatedWayValues"
> & {
  /** 詳細を見ている道（ポップアップが開いている間だけ非null）。 */
  inspectedWayId: number | null;
};

// map.setStyle()は基礎地図タイルのキャッシュクリア後の再読み込みに使うが、これは
// カスタムソース/レイヤーを含むスタイル全体を差し替えるため、こちらで追加した
// ルート/ハロー/風/地域レイヤーがすべて消える。style.loadイベント後にこの関数で
// 現在の表示状態から全レイヤーを作り直す。標高・路面はいずれもタイルソースのため、
// 再取得は不要（キャッシュがクリアされていれば次のタイル要求で自動的に新しいタイルが
// 生成される）。
//
// **再描画で失われる副作用を持つ描画は、必ずここから辿れる位置へ置くこと**（ソース・
// レイヤーの追加だけでなく、filter・feature-state・visibilityで持つ表示状態も含む）。
// 辿れないものはsetStyle()後に作り直されず、押した人の地図から消えたまま戻らない。
//
// カメラは動かさない——再描画は見た目を作り直すだけで、表示範囲は利用者の操作に属する
// （フィットは「候補一覧が変わったとき」だけ、という下部effectの取り決めを破らない）。
/** 地図に載るもの全部の入力。**実行時にしか決まらない値だけ**をここで集め、見た目は
 * 各グループが持つ。 */
type SceneWiringProps = RedrawAllLayersProps &
  Pick<
    MapViewProps,
    | "rampAxes"
    | "dedicatedAxes"
    | "dedicatedWayValueDisplays"
    | "dedicatedWayValueLoading"
    | "dedicatedWayValueHiddenBands"
    | "secondaryAxisCasingLayerIds"
    | "tileVersionsReady"
  >;

type RouteSceneInputs = Pick<
  RedrawAllLayersProps,
  | "routes"
  | "selectedRouteId"
  | "routeLayerOn"
  | "routeStyleModes"
  | "routeStyleModeId"
  | "hiddenRouteLegendKeys"
  | "spliceStretches"
  | "splicedRoute"
  | "experimentSlots"
>;

function routeStateFrom(props: RouteSceneInputs): RouteState {
  const selected = props.routes.find((route) => route.id === props.selectedRouteId) ?? null;
  // モードが1つも配られていない間（軸カタログの取得前）は、色分けの指定が無い状態として
  // 参考線と同じ単色で描く。
  const mode =
    props.routeStyleModes.length > 0 ? getRouteStyleMode(props.routeStyleModes, props.routeStyleModeId) : null;
  const segments = props.routeLayerOn ? (selected?.segments ?? []) : [];
  const bands = props.routeLayerOn ? (props.spliceStretches ?? []) : [];
  const composite = props.routeLayerOn ? (props.splicedRoute ?? null) : null;
  const hiddenBandFilter =
    mode === null
      ? null
      : (buildLegendFilterExpression(mode.legend, props.hiddenRouteLegendKeys) as maplibregl.FilterSpecification | null);
  return {
    visible: props.routeLayerOn,
    candidates: props.routes.map((route) => ({
      routeId: route.id,
      path: route.geometry.coordinates as unknown as RoutePath,
    })),
    selectedRouteId: props.selectedRouteId,
    segments: segments.map((segment) => {
      const { geometry, ...properties } = segment;
      return {
        // 道なりの形が無い区間（2点未満のEdge等）は、始点と終点を結ぶ直線で代替する。
        path: (geometry?.coordinates ?? [
          [segment.start_longitude, segment.start_latitude],
          [segment.end_longitude, segment.end_latitude],
        ]) as unknown as RoutePath,
        properties,
      };
    }),
    segmentColor: (mode?.colorExpression ?? LENS_NEUTRAL_COLOR) as maplibregl.ExpressionSpecification,
    ...(hiddenBandFilter === null ? {} : { hiddenBandFilter }),
    spliceBands: bands.map((band) => ({
      path: band.coordinates as unknown as RoutePath,
      selected: band.taken,
      properties: { index: band.index },
    })),
    composite: composite !== null && composite.length > 1 ? { path: composite as unknown as RoutePath } : null,
    comparisonSlots: props.experimentSlots.map((slot) => ({
      path: slot.topCandidate.geometry.coordinates as unknown as RoutePath,
      color: slot.color,
    })),
    arrowIconImage: ROUTE_ARROW_ICON_ID,
  };
}

/** 評価軸の段。**上の段から順に**並べる——色式は最初に当たった段を採るため。 */
function rampAxisBands(axis: RampAxis): AxisBand[] {
  const count = axis.thresholds.length + 1;
  return Array.from({ length: count }, (_, index) => ({
    key: legendBandKey(index),
    lowerBound: index === 0 ? Number.NEGATIVE_INFINITY : (axis.thresholds[index - 1] as number),
    color: rampColorForBand(index, count),
  })).reverse();
}

function dedicatedAxisBands(display: DedicatedWayValueDisplay): AxisBand[] {
  const boundaries = display.boundaries ?? DEFAULT_DIFFICULTY_BOUNDARIES;
  const colors = bandColorsFor(display.kind, boundaries);
  return Array.from({ length: boundaries.length + 1 }, (_, index) => ({
    key: legendBandKey(index),
    lowerBound: index === 0 ? Number.NEGATIVE_INFINITY : (boundaries[index - 1] as number),
    color: colors[index] ?? COLOR_UNKNOWN,
  })).reverse();
}

function axisStateFrom(props: SceneWiringProps, sourceLayer: string | null): AxisLineState {
  const casing = new Set(props.secondaryAxisCasingLayerIds);
  const ramp = props.rampAxes.map((axis) => ({
    axisId: axis.axisId,
    visible: props.axisVisibility[axisMapLayerId(axis.axisId)] === true,
    bands: rampAxisBands(axis),
    value: { kind: "tile" as const, expression: buildAxisRampValueExpression(axis) },
    hiddenBandKeys: props.staticLegendHiddenKeysByAxis[axis.axisId] ?? [],
    underlay: casing.has(axisMapLayerId(axis.axisId)),
  }));
  const dedicated = props.dedicatedAxes.map((axis) => {
    const display = props.dedicatedWayValueDisplays?.get(axis.axisId) ?? DEFAULT_DEDICATED_WAY_VALUE_DISPLAY;
    return {
      axisId: axis.axisId,
      visible: props.dedicatedWayValueVisibility[dedicatedWayValueMapLayerId(axis.axisId)] === true,
      bands: dedicatedAxisBands(display),
      value: {
        kind: "delivered" as const,
        values: props.dedicatedWayValues.get(axis.axisId) ?? new Map<string, number>(),
        loading: props.dedicatedWayValueLoading?.get(axis.axisId) === true,
      },
      hiddenBandKeys: props.dedicatedWayValueHiddenBands?.get(axis.axisId) ?? [],
      underlay: false,
    };
  });
  return { axes: [...ramp, ...dedicated], sourceLayer };
}

/** 届いている中身を、要素の鍵（`${チップid}/${ソース}`）で引ける形へ移す。 */
function weatherStateFrom(props: SceneWiringProps): WeatherState {
  const shown = new Map<string, { visible: boolean; payload?: WeatherPayload }>();
  for (const [groupId, group] of Object.entries(props.dynamicWeather)) {
    if (group === undefined) continue;
    for (const [sourceId, source] of Object.entries(group)) {
      if (source === undefined) continue;
      shown.set(`${groupId}/${sourceId}`, {
        visible: source.visible,
        ...(source.payload === undefined || source.payload === null
          ? {}
          : { payload: weatherPayloadFrom(source.payload) }),
      });
    }
  }
  return { shown };
}

function weatherPayloadFrom(payload: DynamicWeatherRenderPayload): WeatherPayload {
  switch (payload.kind) {
    case "rasterTile":
    case "vectorTile":
      // 配信元のタイルは自前のプロトコル経由で取りに行く（空タイルの肩代わり・失敗の観測）。
      return { kind: payload.kind, tiles: [withJmaTileProtocol(payload.tileUrlTemplate)] };
    case "gridFill":
    case "gridMark":
      return { kind: payload.kind, data: payload.geojson };
  }
}

export function sceneInputsFrom(props: SceneWiringProps): SceneInputs {
  // 世代が届く前にタイルのソースを作ると、世代の違う中身がブラウザのキャッシュへ載る。
  const tilesReady = props.tileVersionsReady && hasTileVersions();
  const visible = { ...props.staticLayerVisibility, ...props.dedicatedWayValueVisibility, ...props.axisVisibility };
  const hiddenKeys = { ...props.roadHiddenKeysByMode, ...props.staticLegendHiddenKeysByAxis };
  return {
    area: {
      visible,
      tileOrigin: tileBaseUrl(),
      landcoverTileUrl: landcoverTileUrl(),
    },
    road: {
      tiles: tilesReady
        ? {
            urls: [roadSurfaceTileUrl()],
            sourceLayer: ROAD_TILE_SOURCE_LAYER,
            minZoom: ROAD_TILE_MIN_ZOOM,
            maxZoom: ROAD_TILE_MAX_ZOOM,
          }
        : null,
      visible,
      hiddenKeys,
      inspectedWayId: props.inspectedWayId,
    },
    axis: axisStateFrom(props, tilesReady ? ROAD_TILE_SOURCE_LAYER : null),
    point: {
      tiles: tilesReady
        ? {
            poi: [poiTileUrl()],
            accident: [accidentTileUrl()],
            poiSourceLayer: STOP_POI_SOURCE_LAYER,
            accidentSourceLayer: ACCIDENT_TILE_SOURCE_LAYER,
            minZoom: ROAD_TILE_MIN_ZOOM,
            maxZoom: ROAD_TILE_MAX_ZOOM,
          }
        : null,
      visible,
      hiddenKeys,
    },
    weather: weatherStateFrom(props),
    route: routeStateFrom(props),
  };
}

/** 記号に要る絵。**出す前に登録しないと記号が描かれない。** */
const SCENE_ICONS: readonly { id: string; create: () => ImageData }[] = [
  ...WEATHER_ICONS,
  { id: ROUTE_ARROW_ICON_ID, create: createRouteArrowIcon },
];

/** 地図へ当てた宣言を地図ごとに覚える。スタイルを差し替えた後は `reset` で作り直す。 */
const appliedScene = new WeakMap<MapLibreMap, MapScene>();

export function applyScene(map: MapLibreMap, scene: MapScene, options: { reset?: boolean } = {}) {
  runWhenStyleReady(map, () => {
    for (const icon of SCENE_ICONS) {
      if (!map.hasImage(icon.id)) map.addImage(icon.id, icon.create(), { sdf: true });
    }
    applyMapScene(map, {
      scene,
      previous: options.reset === true ? EMPTY_MAP_SCENE : (appliedScene.get(map) ?? EMPTY_MAP_SCENE),
      areaLayerBeforeId: areaLayerAnchor(map),
    });
    appliedScene.set(map, scene);
  });
}

/** スタイルを差し替えた後、いまの状態から全部を作り直す。
 *
 * カメラは動かさない——作り直すのは見た目だけで、表示範囲は利用者の操作に属する。 */
export function redrawAllLayers(map: MapLibreMap, props: SceneWiringProps) {
  applyScene(map, buildMapScene(sceneInputsFrom(props)), { reset: true });
}

/** 画面の状態を地図へ当てる。**ここが唯一の適用の入口**。
 *
 * 状態 → 各家族の入力（`sceneInputsFrom`）→ 望ましい並び（`buildMapScene`）→
 * 差分を当てる（`applyMapScene`）の1本道。スタイルを差し替えた後の作り直しも同じ道を通り、
 * 前回との差分ではなく空から当て直す（`applyScene`の`reset`）だけが違う。
 *
 * **再描画で失われる副作用を持つ描画は、必ずここから辿れる位置へ置く。** レイヤーの
 * 追加だけでなく、filter・feature-state・visibilityで持つ表示状態も同じ。辿れないものは
 * `setStyle()`後に作り直されず、押した人の地図から消えたままになる。
 *
 * カメラは動かさない——作り直しは見た目を戻すだけで、表示範囲は利用者のもの。
 */
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";

import type { MapLayerVisibility } from "@/features/map/layers/mapLayers";
import { rampColorForBand, type DedicatedWayValueAxis, type RampAxis } from "@/lib/mapDisplay/axisLayers";
import { debugLog } from "@/lib/debugLog";
import type { DedicatedWayValueDisplay } from "@/lib/mapDisplay/dedicatedWayValueLayer";
import type {
  DynamicWeatherGroupState,
  DynamicWeatherLayerId,
  DynamicWeatherRenderPayload,
} from "@/features/map/layers/dynamicWeather";
import { withJmaTileProtocol } from "@/features/map/layers/jmaTileProtocol";
import { legendBandKey } from "@/lib/mapDisplay/mapColorLegend";
import { areaLayerAnchor, prepareBasemapForAreaLayers, runWhenStyleReady } from "@/features/map/layers/mapStyleOps";
import { primaryAttributeIdsToLayerIds } from "@/features/map/layers/primaryAttributes";
import { ROUTE_ARROW_ICON_ID, createRouteArrowIcon } from "@/features/map/layers/routeArrowIcon";
import { LENS_NEUTRAL_COLOR, type LensId, type RouteStyleMode } from "@/lib/mapDisplay/routeStyleModes";
import type { SecondaryAxisSummary } from "@/lib/secondaryAxes";
import type { ExperimentSlot } from "@/types/experimentSlot";
import type { RouteCandidate } from "@/types/route";
import { bandColorsFor, DEFAULT_DIFFICULTY_BOUNDARIES } from "@/lib/mapDisplay/valueScale";
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
export const ROAD_TILE_SOURCE_LAYER = regionTileConfig.road_surface.layer_name;
export const ACCIDENT_TILE_SOURCE_LAYER = regionTileConfig.accident.layer_name;
export const STOP_POI_SOURCE_LAYER = regionTileConfig.poi.stop_poi_layer_name;

import { applyMapScene } from "./applyMapScene";
import { buildAxisRampUnknownExpression, buildAxisRampValueExpression } from "./groups/axisLines";
import { buildLegendFilterExpression, COLOR_UNKNOWN } from "./sceneBuilders";
import type { SceneInputs } from "./buildScene";
import type { AxisBand, AxisLineState } from "@/features/map/scene/groups/axisLines";
import type { RoutePath, RouteState } from "@/features/map/scene/groups/routes";
import { WEATHER_ICONS, type WeatherPayload, type WeatherState } from "@/features/map/scene/groups/weather";
import { EMPTY_MAP_SCENE, type MapScene } from "./mapScene";

/** 乗り換えられる区間1本ぶんの入力。`index`は押されたときに呼び出し側が見分ける値。 */
export interface SpliceStretchInput {
  readonly index: number;
  readonly coordinates: readonly GeoJSON.Position[];
}

/** 凡例の保存先id → 隠した行の鍵。 */
export type HiddenLegendKeys = Readonly<Record<string, readonly string[]>>;

/** 地図の見え方の状態。**状態そのものだけ**で、ここから導けるもの（どのレイヤーを出すか・
 * 家族ごとの隠した行・下敷き）はこのファイルが導く。 */
export interface SceneLook {
  readonly layerVisibility: MapLayerVisibility;
  readonly dynamicWeather: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>>;
  /** ルート線の色分けのモード。 */
  readonly lens: LensId;
  /** 全道路を塗っている軸（塗っていなければnull）。 */
  readonly paintedAxisId: LensId | null;
  /** 専用配信軸ごとの取得結果。 */
  readonly dedicatedWayValues: ReadonlyMap<string, { values: ReadonlyMap<string, number>; loading: boolean }>;
  readonly hiddenLegendKeys: HiddenLegendKeys;
}

/** 地図に載るもの全部の入力。**実行時にしか決まらない値だけ**をここで集め、見た目は
 * 各グループが持つ。**sceneの側で宣言する**——上位の画面部品のpropsから借りると、
 * sceneと画面部品が互いをimportし合い、sceneの語彙が画面部品の都合で決まる。 */
type SceneWiringProps = {
  readonly look: SceneLook;
  readonly catalog: {
    readonly rampAxes: readonly RampAxis[];
    readonly dedicatedAxes: readonly DedicatedWayValueAxis[];
    readonly routeStyleModes: readonly RouteStyleMode[];
    readonly secondaryAxes: readonly SecondaryAxisSummary[];
  };
  readonly routes: readonly RouteCandidate[];
  readonly selectedRouteId: string | null;
  /** 比較相手が別の道を通る区間。空/未指定なら帯を出さない。 */
  readonly spliceStretches?: readonly SpliceStretchInput[];
  /** 編集中に「いま作っているルート」として描く座標列。 */
  readonly splicedRoute?: readonly GeoJSON.Position[] | null;
  readonly experimentSlots: readonly ExperimentSlot[];
  /** タイル世代が届いたか。 */
  readonly tileVersionsReady: boolean;
  /** 詳細を見ている道（ポップアップが開いている間だけ非null）。 */
  readonly inspectedWayId: number | null;
};

const NO_KEYS: readonly string[] = [];

function routeStateFrom(props: SceneWiringProps): RouteState {
  const { look } = props;
  const visible = look.layerVisibility.route === true;
  const selected = props.routes.find((route) => route.id === props.selectedRouteId) ?? null;
  // モードが1つも配られていない間（軸カタログの取得前）は、色分けの指定が無い状態として
  // 参考線と同じ単色で描く。
  const modes = props.catalog.routeStyleModes;
  const mode = modes.length > 0 ? getRouteStyleMode(modes, look.lens) : null;
  const segments = visible ? (selected?.segments ?? []) : [];
  const bands = visible ? (props.spliceStretches ?? []) : [];
  const composite = visible ? (props.splicedRoute ?? null) : null;
  const hiddenBandFilter =
    mode === null
      ? null
      : (buildLegendFilterExpression(
          mode.legend,
          look.hiddenLegendKeys[look.lens] ?? NO_KEYS,
        ) as maplibregl.FilterSpecification | null);
  return {
    visible,
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
    ...(mode?.noDataExpression === undefined
      ? {}
      : { segmentNoData: mode.noDataExpression as maplibregl.ExpressionSpecification }),
    ...(hiddenBandFilter === null ? {} : { hiddenBandFilter }),
    spliceBands: bands.map((band) => ({
      path: band.coordinates as unknown as RoutePath,
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

/** 下敷きで描くramp軸。その軸の材料（一次属性の表示レイヤー）が1つでも出ている間は、材料の
 * 線を隠さないよう下へ敷く。 */
function underlaidAxisIds(props: SceneWiringProps): ReadonlySet<string> {
  const visible = props.look.layerVisibility;
  return new Set(
    props.catalog.secondaryAxes
      .filter((axis) => primaryAttributeIdsToLayerIds(axis.primaryAttributeIds).some((id) => visible[id]))
      .map((axis) => axis.axisId),
  );
}

function axisStateFrom(props: SceneWiringProps, sourceLayer: string | null): AxisLineState {
  const { look } = props;
  const underlaid = underlaidAxisIds(props);
  const hiddenOf = (axisId: string) => look.hiddenLegendKeys[axisId] ?? NO_KEYS;
  const ramp = props.catalog.rampAxes.map((axis) => ({
    axisId: axis.axisId,
    visible: axis.axisId === look.paintedAxisId,
    bands: rampAxisBands(axis),
    value: {
      kind: "tile" as const,
      expression: buildAxisRampValueExpression(axis),
      unknown: buildAxisRampUnknownExpression(axis),
    },
    hiddenBandKeys: hiddenOf(axis.axisId),
    underlay: underlaid.has(axis.axisId),
  }));
  const dedicated = props.catalog.dedicatedAxes.map((axis) => {
    const delivered = look.dedicatedWayValues.get(axis.axisId);
    return {
      axisId: axis.axisId,
      visible: axis.axisId === look.paintedAxisId,
      bands: dedicatedAxisBands(axis.display),
      value: {
        kind: "delivered" as const,
        values: delivered?.values ?? new Map<string, number>(),
        loading: delivered?.loading === true,
      },
      hiddenBandKeys: hiddenOf(axis.axisId),
      underlay: false,
    };
  });
  return { axes: [...ramp, ...dedicated], sourceLayer };
}

/** 届いている中身を、要素の鍵（`${チップid}/${ソース}`）で引ける形へ移す。 */
function weatherStateFrom(props: SceneWiringProps): WeatherState {
  const shown = new Map<string, { visible: boolean; payload?: WeatherPayload }>();
  for (const [groupId, group] of Object.entries(props.look.dynamicWeather)) {
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
  // 家族はどれも自分の役割の鍵だけを読むため、状態をそのまま渡す。
  const visible = props.look.layerVisibility;
  const hiddenKeys = props.look.hiddenLegendKeys;
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
    prepareBasemapForAreaLayers(map);
    applyMapScene(map, {
      scene,
      previous: options.reset === true ? EMPTY_MAP_SCENE : (appliedScene.get(map) ?? EMPTY_MAP_SCENE),
      areaLayerBeforeId: areaLayerAnchor(map),
    });
    appliedScene.set(map, scene);
  });
}

function getRouteStyleMode(modes: readonly RouteStyleMode[], id: LensId): RouteStyleMode {
  const found = modes.find((mode) => mode.id === id);
  if (found) return found;
  // 軸の非公開等でidのモードが消えていたら先頭へ倒す。選択中の色分けが黙って変わるため警告を残す。
  debugLog(
    "map:route-style-mode",
    `route style mode "${id}" not found, falling back to "${modes[0]?.id ?? "(no modes)"}"`,
    { requestedId: id, availableIds: modes.map((mode) => mode.id) },
    "warn",
  );
  return modes[0];
}

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { buildPointPopupContent } from "@/features/map/MapView/pointPopup";
import RoadInspectorPopup from "@/features/map/MapView/RoadInspectorPopup";
import type { RoadSurfacePopupProperties } from "@/features/map/MapView/roadFacts";
import * as maplibregl from "maplibre-gl";

import { configureMaplibreWorker } from "@/features/map/maplibreWorker";
import type {
  ErrorEvent as MapLibreErrorEvent,
  Map as MapLibreMap,
  Marker,
  MapLayerMouseEvent,
  MapMouseEvent,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type {
  Coordinates,
  LocationSource,
  PinRole,
  RouteCandidate,
  RoutePreferenceWeights,
  RouteSegmentDetail,
  SelectedRouteSegment,
} from "@/types/route";
import type { ExperimentSlot } from "@/types/experimentSlot";
import { ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM } from "@/services/regionApi";
import type { RideConditions } from "@/services/regionApi";
import { tileContainingLonLat, type TileXY } from "@/features/map/layers/dynamicWayValues";
import {
  ORIGIN_MARK_COLOR,
  ORIGIN_MARK_FALLBACK_COLOR,
  PIN_MARK_BACKGROUND,
  pinMarkHtml,
} from "@/lib/mapDisplay/pinMarks";
import {
  buildMapLayers,
  type MapLayerDataSource,
  type MapLayerDescriptor,
  type LayerDataStatusByLayer,
  type MapLayerId,
} from "@/features/map/layers/mapLayers";
import { apiPath } from "@/lib/apiPath";
import { tileBaseUrl } from "@/lib/tileBaseUrl";
import { resetBasemapAreaLayerPreparation, runWhenStyleReady } from "@/features/map/layers/mapStyleOps";
import {
  ACCIDENT_TILE_SOURCE_LAYER,
  applyScene,
  ROAD_TILE_SOURCE_LAYER,
  sceneInputsFrom,
  STOP_POI_SOURCE_LAYER,
  type SpliceStretchInput,
} from "@/features/map/scene/applyToMap";
import { interactiveSceneLayerIds, sceneLayerIdsForHitTarget, type MapScene } from "@/features/map/scene/mapScene";
import {
  ROUTE_HIT_TARGET,
  ROUTE_HIT_TARGET_SEGMENT,
  ROUTE_HIT_TARGET_SPLICE_BAND,
} from "@/features/map/scene/groups/routes";
import { buildMapScene, type SceneInputs } from "@/features/map/scene/buildScene";
import { POINT_LAYERS, pointSourceId } from "@/features/map/scene/groups/points";
import { AREA_SOURCE_ID } from "@/features/map/scene/groups/areaRasters";
import { ROAD_LINE_SOURCE_ID } from "@/features/map/scene/groups/roadLines";
import { sceneLayerId } from "@/features/map/scene/sceneBuilders";

/** 押された点のレイヤーidから、その点の宣言を引く。idは役割から決まるので写しではない。 */
const POINT_LAYER_BY_SCENE_ID = new Map(
  POINT_LAYERS.map((layer) => [sceneLayerId(pointSourceId(layer.tile_kind), layer.attr_id), layer]),
);

/** ルート線の当たり判定レイヤー。**idは scene が決める**ので、当たり判定の名前で引く。 */
function routeHitLayerId(scene: MapScene, target: string): string | undefined {
  return sceneLayerIdsForHitTarget(scene, target)[0];
}
import { axisMapLayerId } from "@/lib/mapDisplay/axisLayers";
import { mapDisplay } from "@/types/generated/mapDisplay";
import type { MapLook } from "@/features/map/view/mapLook";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { useTileVersionsReady } from "@/features/map/useTileVersionsReady";
import { useLayerDataStatus } from "@/features/map/MapView/useLayerDataStatus";
import { useJmaTileIndex } from "@/features/map/useJmaTileIndex";
import { registerJmaTileProtocol } from "@/features/map/layers/jmaTileProtocol";
import { debugLog } from "@/lib/debugLog";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

// 基礎地図のスタイルJSON。中のタイル・スプライト・グリフのURLはbackendがBASEMAP_PUBLIC_BASE_URLで
// 組み立てるため、`tileBaseUrl()`と同じオリジンを指すよう揃える。
const MAP_STYLE_PATH = apiPath("/api/basemap/{path}", { path: "styles/liberty" });
function mapStyleUrl(): string {
  return `${tileBaseUrl()}${MAP_STYLE_PATH}`;
}

// 出発地点は現在地の記号（十字線と中心の点）を白い円に乗せる。左右対称なので、アンカーは地点＝中心（"center"）。
function createOriginMarkerElement(color: string): HTMLDivElement {
  const el = document.createElement("div");
  el.style.cssText =
    "width:32px; height:32px; border-radius:50%; background:" +
    PIN_MARK_BACKGROUND.origin +
    "; display:flex; " +
    "align-items:center; justify-content:center; box-shadow:0 1px 4px rgba(0,0,0,0.4); " +
    "touch-action:none; cursor:grab;";
  el.innerHTML = pinMarkHtml("origin", { size: 20, color });
  return el;
}

// 経由地・目的地のピン。3つの地点はどれもつかんで動かせるため、出発地と同じ丸いバッジで揃える。白縁と影は
// どの配色の上でも輪郭が消えないため、touch-action:noneは指の起点がピンに乗ってもパンとして確定させるため。
function createPointMarkerElement(role: PinRole, label?: string): HTMLDivElement {
  const el = document.createElement("div");
  const background = PIN_MARK_BACKGROUND[role];
  el.innerHTML = pinMarkHtml(role, { label });
  el.style.cssText =
    `width:26px; height:26px; border-radius:50%; background:${background}; color:#fff; ` +
    "font-size:13px; font-weight:bold; display:flex; align-items:center; justify-content:center; " +
    "border:2px solid #fff; box-shadow:0 1px 4px rgba(0,0,0,0.4); touch-action:none; cursor:grab;";
  return el;
}

// マーカーをドラッグした直後は、同じ操作の終わりにclickも飛ぶ。つかんで動かしただけで
// 削除・解除が起きないよう、ドラッグ由来の1回を読み飛ばす。
function bindDragAwareClick(marker: maplibregl.Marker, element: HTMLElement, onClick: () => void): void {
  let dragged = false;
  marker.on("dragstart", () => {
    dragged = true;
  });
  element.addEventListener("click", (event) => {
    event.stopPropagation();
    if (dragged) {
      dragged = false;
      return;
    }
    onClick();
  });
}

type LayerDataSource = { key: MapLayerId; sourceId: string; sourceLayer?: string };

// 初期表示の覆い（「地図を読み込み中…」）を出しておく上限。覆いは基礎地図が描けた時点（"load"）で外すので、
// これは基礎地図のタイルが止まって"load"が来ないときの保険。
const INITIAL_TILES_OVERLAY_MAX_MS = 6000;

/** 情報源の名前→MapLibreの(source, source-layer)。レイヤーごとではなく情報源ごとの表で、配信元を増やしたときだけ
 * 伸びる。source-layerを持たないラスタは取得失敗だけを見て、空かどうかは判定しない。 */
const TILE_SOURCE_BY_DATA_SOURCE: Record<
  Exclude<MapLayerDataSource, "ownFetch">,
  { sourceId: string; sourceLayer?: string }
> = {
  road_surface: { sourceId: ROAD_LINE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
  accident: { sourceId: pointSourceId("accident"), sourceLayer: ACCIDENT_TILE_SOURCE_LAYER },
  poi: { sourceId: pointSourceId("poi"), sourceLayer: STOP_POI_SOURCE_LAYER },
  gsiRelief: { sourceId: AREA_SOURCE_ID.elevation },
  gsiTerrain: { sourceId: AREA_SOURCE_ID.hillshade },
  landcoverRaster: { sourceId: AREA_SOURCE_ID.landcover },
};

/** レイヤーごとのデータ取得状態の算出元。母集団はレイヤーカタログそのもの。自前のJSで取りに行くもの（`ownFetch`）は
 * MapLibreのソースイベントでは観測できないため除く（取得した側が状態を出す）。 */
function buildLayerDataSources(layers: readonly MapLayerDescriptor[]): readonly LayerDataSource[] {
  return layers.flatMap((layer) =>
    layer.dataSource === "ownFetch" ? [] : [{ key: layer.id, ...TILE_SOURCE_BY_DATA_SOURCE[layer.dataSource] }],
  );
}

function computeRouteBounds(routes: RouteCandidate[]): maplibregl.LngLatBounds {
  const bounds = new maplibregl.LngLatBounds();
  for (const route of routes) {
    for (const [lng, lat] of route.geometry.coordinates) {
      bounds.extend([lng, lat]);
    }
  }
  return bounds;
}

// ルート全体を収めるときの基本余白（全辺）。
const ROUTE_FIT_BASE_PADDING_PX = 40;
// フィット後に必ず残す可視領域の幅・高さ。覆うUIが大きいと、余白同士が地図を食い尽くしてズームが破綻する。
const ROUTE_FIT_MIN_VISIBLE_PX = 80;

/** 地図キャンバスの上に重なるUIで覆われている辺ごとの高さ(px)。 */
export interface RouteFitObscuredPx {
  top?: number;
  bottom?: number;
  left?: number;
  right?: number;
}

/** 覆われている高さを基本余白へ足したフィット用paddingを返す。対向する2辺の合計が
 * 地図の幅・高さを食い尽くす場合は、可視領域がROUTE_FIT_MIN_VISIBLE_PX残るところまで
 * その2辺を同じ比率で縮める。 */
function computeRouteFitPadding(
  obscured: RouteFitObscuredPx | undefined,
  canvas: { width: number; height: number },
): { top: number; bottom: number; left: number; right: number } {
  const base = ROUTE_FIT_BASE_PADDING_PX;
  const padding = {
    top: base + (obscured?.top ?? 0),
    bottom: base + (obscured?.bottom ?? 0),
    left: base + (obscured?.left ?? 0),
    right: base + (obscured?.right ?? 0),
  };

  const shrink = (a: number, b: number, size: number): [number, number] => {
    const available = Math.max(0, size - ROUTE_FIT_MIN_VISIBLE_PX);
    const total = a + b;
    if (total <= available) return [a, b];
    const ratio = total > 0 ? available / total : 0;
    return [a * ratio, b * ratio];
  };

  [padding.top, padding.bottom] = shrink(padding.top, padding.bottom, canvas.height);
  [padding.left, padding.right] = shrink(padding.left, padding.right, canvas.width);
  return padding;
}

function fitBoundsToRoutes(map: MapLibreMap, routes: RouteCandidate[], obscured?: RouteFitObscuredPx) {
  if (routes.length === 0) return;

  const bounds = computeRouteBounds(routes);

  runWhenStyleReady(map, () => {
    const canvas = map.getCanvas();
    map.fitBounds(bounds, {
      padding: computeRouteFitPadding(obscured, { width: canvas.clientWidth, height: canvas.clientHeight }),
    });
  });
}

// 区間の当たり判定は見た目の線より広いため、押した地点の印を区間の線上の最寄りの点へ寄せる。区間の距離なら
// 経緯度を平面とみなした近似で足りる。
function nearestPointOnLineString(
  coordinates: readonly (readonly [number, number])[],
  point: readonly [number, number],
): [number, number] {
  if (coordinates.length === 0) return [point[0], point[1]];
  if (coordinates.length === 1) return [coordinates[0][0], coordinates[0][1]];

  let best: [number, number] = [coordinates[0][0], coordinates[0][1]];
  let bestDistSq = Infinity;

  for (let i = 0; i < coordinates.length - 1; i++) {
    const [ax, ay] = coordinates[i];
    const [bx, by] = coordinates[i + 1];
    const [px, py] = point;
    const abx = bx - ax;
    const aby = by - ay;
    const lengthSq = abx * abx + aby * aby;
    const t = lengthSq === 0 ? 0 : Math.min(1, Math.max(0, ((px - ax) * abx + (py - ay) * aby) / lengthSq));
    const cx = ax + t * abx;
    const cy = ay + t * aby;
    const dx = px - cx;
    const dy = py - cy;
    const distSq = dx * dx + dy * dy;
    if (distSq < bestDistSq) {
      bestDistSq = distSq;
      best = [cx, cy];
    }
  }
  return best;
}

interface MapViewProps {
  routes: RouteCandidate[];
  selectedRouteId: string | null;
  // 比較相手が別の道を通る区間。空/未指定なら帯を出さない。
  spliceStretches?: readonly SpliceStretchInput[];
  /** 編集中に「いま作っているルート」として描く座標列（編集していなければ省略）。 */
  splicedRoute?: readonly GeoJSON.Position[] | null;
  /** 乗り換えられる区間の帯をタップしたときに呼ばれる（`SpliceStretchInput.index`）。
   * 選ぶ操作の中心を地図へ置くためのもの——パネルの行だけで選ばせると、どの行がどの帯かを
   * 目で対応づける必要がある。 */
  onSpliceStretchSelect?: (index: number) => void;
  location: Coordinates;
  /** 出発地点の色。位置が取れず既定の地点（"default"）のときだけ灰色にする。 */
  locationSource: LocationSource;
  /** 地図の見え方（`features/map/view/useMapView`）。状態そのものと地図からのイベントだけで、
   * 軸カタログ・タイル世代のような共有の源泉から導けるものはここで読む。 */
  look: MapLook;
  /** 地図を塗るのに使っている走行の条件。道を押したときの内訳にも同じ値を渡す（揃えないと色と数字が食い違う）。 */
  rideConditions?: RideConditions;
  /** 利用者がいま設定している重み（ルート生成へ送るのと同じもの）。道の詳細の評価に使う。nullなら既定の重み。 */
  routePreference?: RoutePreferenceWeights | null;
  /** 実験スロット。デバッグモードOFFの間は空。 */
  experimentSlots: ExperimentSlot[];
  /** 押して選んでいる区間。地図は押した地点に印を立てるだけで、内訳は下部のシートが出す（地図上の
   * ポップアップはモバイルでシートに隠れる）。 */
  selectedRouteSegment: SelectedRouteSegment | null;
  /** ルートの区間を押したとき・印を押して選択を外したとき。 */
  onRouteSegmentSelect: (selection: SelectedRouteSegment | null) => void;
  /** 経由地（通る順）。 */
  waypoints: Coordinates[];
  /** 武装中の役割。nullの間、地図のタップはピンを置かない（地物の詳細表示のみ）。 */
  armedPinRole: PinRole | null;
  /** 地点（出発地・経由地・目的地）をつかんで動かす・押して消すことを受け付けるか。
   * 地図でできることは、いま見ているパネルが持つ操作だけにする（地点は「ルート設定」の
   * 条件タブ）。falseの間、マーカーは表示だけで動かせない。 */
  pointEditingEnabled: boolean;
  /** 武装中の役割の地点として、タップした座標を渡す。 */
  onPinPlace: (role: PinRole, coordinates: Coordinates) => void;
  /** 経由地マーカークリックで呼ばれる（該当indexを削除）。 */
  onWaypointRemove: (index: number) => void;
  /** 経由地マーカーをドラッグして動かしたときに呼ばれる（該当indexの座標を差し替え）。 */
  onWaypointMove: (index: number, coordinates: Coordinates) => void;
  /** 目的地（あれば片道のルート）。 */
  destination: Coordinates | null;
  /** 目的地マーカークリックで呼ばれる（解除）。 */
  onDestinationClear: () => void;
  /** 地図の上に重なるUIで覆われている辺ごとの高さ(px)をいま測る。ルートを収めるとき、覆われた所へ収めないため。
   * レイアウトを持つ呼び出し側が測る。 */
  measureRouteFitObscuredPx?: () => RouteFitObscuredPx | undefined;
}

export default function MapView({
  routes,
  selectedRouteId,
  spliceStretches,
  splicedRoute,
  onSpliceStretchSelect,
  location,
  locationSource,
  look,
  rideConditions,
  routePreference = null,
  experimentSlots,
  selectedRouteSegment,
  onRouteSegmentSelect,
  waypoints,
  armedPinRole,
  pointEditingEnabled,
  onPinPlace,
  onWaypointRemove,
  onWaypointMove,
  destination,
  onDestinationClear,
  measureRouteFitObscuredPx,
}: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  // 出発地点の印に当てた色の元。Markerは位置の更新で色を変えられないため、色が変わるときだけ作り直す。
  const appliedMarkerSourceRef = useRef<LocationSource | null>(null);
  const waypointMarkersRef = useRef<Marker[]>([]);
  const destinationMarkerRef = useRef<Marker | null>(null);
  const selectedSegmentMarkerRef = useRef<Marker | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  // 道を押したときの詳細はReactで描き、MapLibreのPopupへportalで差し込む。
  const [roadPopup, setRoadPopup] = useState<{
    lngLat: [number, number];
    properties: RoadSurfacePopupProperties;
    // 押した瞬間のタイル（開いたままズームしても、押した道のタイルを指す）。
    tile: TileXY;
  } | null>(null);
  const [roadPopupContainer, setRoadPopupContainer] = useState<HTMLDivElement | null>(null);
  const catalog = useAxisCatalog();
  const tileVersionsReady = useTileVersionsReady();
  const mapLayerCatalog = useMemo(
    () => buildMapLayers(catalog.rampAxes, catalog.dedicatedAxes),
    [catalog.rampAxes, catalog.dedicatedAxes],
  );
  const layerDataSources = useMemo(() => buildLayerDataSources(mapLayerCatalog), [mapLayerCatalog]);
  // 詳細を見ている道。強調も scene の一部として当てる。
  const inspectedWayId = roadPopup?.properties.osm_way_id ?? null;
  // 地図に載るもの全部の入力。**ここが scene の唯一の組み立て口**。
  const sceneInputs = useMemo<SceneInputs>(
    () =>
      sceneInputsFrom({
        look,
        catalog,
        routes,
        selectedRouteId,
        spliceStretches,
        splicedRoute,
        experimentSlots,
        tileVersionsReady,
        inspectedWayId,
      }),
    [
      look,
      catalog,
      routes,
      selectedRouteId,
      spliceStretches,
      splicedRoute,
      experimentSlots,
      tileVersionsReady,
      inspectedWayId,
    ],
  );
  const scene = useMemo(() => buildMapScene(sceneInputs), [sceneInputs]);
  // 押せるのは scene が当たり判定を宣言したレイヤーだけ。
  const interactiveLayerIds = useMemo(() => interactiveSceneLayerIds(scene), [scene]);
  // スタイルが取れないとMapLibreは"load"ではなく"error"だけを出し、地図は白紙のまま止まる。そのとき案内を出す。
  const [styleLoadFailed, setStyleLoadFailed] = useState(false);
  // スタイルを取り直している間（"style.load"待ち）。最初の"load"は地図の生涯で1度しか来ないため、取り直しの
  // 失敗はこの印で見分ける。
  const styleReloadPendingRef = useRef(false);
  // 最初のタイルが揃うまでの白紙を覆う。
  const [initialTilesLoading, setInitialTilesLoading] = useState(true);
  // 取得状態の算出が見る表示ON/OFF。塗っているramp軸はレンズが決める。
  const layerVisibility = useMemo(
    () => ({
      ...look.layerVisibility,
      ...Object.fromEntries(
        catalog.rampAxes.map((axis) => [axisMapLayerId(axis.axisId), axis.axisId === look.paintedAxisId]),
      ),
    }),
    [look.layerVisibility, look.paintedAxisId, catalog.rampAxes],
  );
  // 地図のイベント（初期化のeffectで一度だけ登録する）とマーカーの操作が、いまのpropsを読むための参照。
  const latestProps = {
    scene,
    look,
    layerVisibility,
    interactiveLayerIds,
    onPinPlace,
    armedPinRole,
    pointEditingEnabled,
    onWaypointRemove,
    onWaypointMove,
    onDestinationClear,
    measureRouteFitObscuredPx,
    onRouteSegmentSelect,
    onSpliceStretchSelect,
  };
  const latest = useRef(latestProps);
  useEffect(() => {
    latest.current = latestProps;
  });
  // 出発地点をドラッグで動かした直後の1回だけ、位置の更新でカメラを動かさない（その地点は既に画面に見えている）。
  const skipNextFlyToRef = useRef(false);

  // スタイルを差し替えた後、いまの宣言を空から当て直す。
  const redrawFromCurrentProps = useCallback((map: MapLibreMap) => {
    applyScene(map, latest.current.scene, { reset: true });
  }, []);

  const getLayerVisibility = useCallback(() => latest.current.layerVisibility, []);
  const onLayerDataStatusChange = useCallback(
    (status: LayerDataStatusByLayer) => latest.current.look.onLayerDataStatusChange(status),
    [],
  );
  const {
    recompute: recomputeLayerDataStatus,
    markSourceErrored,
    clearSourceLoading,
    notifySourceData,
    settleViewport,
  } = useLayerDataStatus({
    mapRef,
    layerDataSources,
    getVisibility: getLayerVisibility,
    onChange: onLayerDataStatusChange,
  });

  // JMAタイルの在否インデックスを定期取得し、空と分かっているタイルの要求を間引く。
  useJmaTileIndex();

  // 地図初期化
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    // どちらもMapを作る前に要る（Mapの生成がWorkerを起こし、スタイルの適用でタイル要求が始まる）。
    configureMaplibreWorker();
    registerJmaTileProtocol();

    // 片付けた後に"idle"が届いても状態を書かない。
    let cancelled = false;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: mapStyleUrl(),
      center: [location.longitude, location.latitude],
      zoom: 13,
      // 常に使うデータの出典は、どのレイヤーを出しているかと関係なく出す（宣言はbackend）。
      attributionControl: { compact: true, customAttribution: [...mapDisplay.alwaysShownAttributions] },
      // デバッグモードの間、MapLibreが出す要求を種別ごとにログする（無効の間debugLogは何もしない）。
      transformRequest: (url, resourceType) => {
        debugLog("map:request", `${resourceType ?? "unknown"} ${url}`);
        return { url };
      },
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;
    debugLog("map:lifecycle", "初期化", { center: [location.longitude, location.latitude], zoom: 13 });

    // 出典の表示は、データが載った時点でMapLibreが開いた状態（全文）にし、地図を一度ドラッグするまで閉じない。
    // その間ほかのUIと重なるため、同じイベントのたびに畳む。
    const attribEl = mapContainerRef.current?.querySelector(".maplibregl-ctrl-attrib");
    function collapseAttribution() {
      attribEl?.classList.remove("maplibregl-compact-show");
    }
    map.on("styledata", collapseAttribution);
    map.on("sourcedata", collapseAttribution);

    // MapLibreの内蔵の追従は、デバッグログの流入とレイアウトの変化が重なると通知を取りこぼし、地図が幅の一部に
    // しか描かれなくなる。コンテナの大きさが変わったら明示的にresizeする。
    const resizeObserver = new ResizeObserver(() => {
      mapRef.current?.resize();
    });
    resizeObserver.observe(mapContainerRef.current);
    // 地物を押すと詳細を出す。**どれかの役割で武装している間だけ**、その1タップは地物を見ずにピンを置く（道の
    // 上を目的地にしたいこともある）。武装していなければピンは増えない（見ているだけの操作で経由地が増えない）。
    function handleClick(e: MapMouseEvent) {
      const armed = latest.current.armedPinRole;
      if (armed) {
        latest.current.onPinPlace(armed, { latitude: e.lngLat.lat, longitude: e.lngLat.lng });
        return;
      }
      // ルートの線は専用のハンドラ（レイヤーへの"click"）が受ける。MapLibreは地図全体の"click"とレイヤーの
      // "click"を両方出すため、ルートの線に当たったらここでは何もしない（道の詳細と同時に開かない）。
      for (const hitLayerId of sceneLayerIdsForHitTarget(latest.current.scene, ROUTE_HIT_TARGET)) {
        if (map.getLayer(hitLayerId) && map.queryRenderedFeatures(e.point, { layers: [hitLayerId] }).length > 0) {
          return;
        }
      }
      const layers = latest.current.interactiveLayerIds.filter((id) => map.getLayer(id));
      if (layers.length === 0) return;
      const features = map.queryRenderedFeatures(e.point, { layers });
      if (features.length === 0) return;

      const feature = features[0];
      // 道はルート結果と同じ「軸ごとの効き方」を見せるためReactの部品で描く。点（事故・POI）は数行の事実だけなので
      // MapLibreのPopupへ直接載せる。
      const point = POINT_LAYER_BY_SCENE_ID.get(feature.layer.id);
      const pointContent = point === undefined ? null : buildPointPopupContent(point, feature.properties);

      popupRef.current?.remove();
      popupRef.current = null;
      if (pointContent !== null) {
        setRoadPopup(null);
        popupRef.current = new maplibregl.Popup({ closeButton: true })
          .setLngLat(e.lngLat)
          .setDOMContent(pointContent)
          .addTo(map);
        return;
      }
      setRoadPopup({
        lngLat: [e.lngLat.lng, e.lngLat.lat],
        properties: feature.properties as unknown as RoadSurfacePopupProperties,
        tile: tileContainingLonLat(e.lngLat.lng, e.lngLat.lat, map.getZoom(), ROAD_TILE_MIN_ZOOM, ROAD_TILE_MAX_ZOOM),
      });
    }

    // 乗り換えられる区間の帯を押したら、その区間の道を選ぶ（選ぶ操作の中心を地図へ置く）。
    function handleSpliceStretchClick(e: MapLayerMouseEvent) {
      const index = e.features?.[0]?.properties?.index;
      if (typeof index !== "number") return;
      popupRef.current?.remove();
      latest.current.onSpliceStretchSelect?.(index);
    }

    function handleRouteSegmentClick(e: MapLayerMouseEvent) {
      const feature = e.features?.[0];
      if (!feature) return;
      // 前に開いた点の詳細が残らないよう閉じる。
      popupRef.current?.remove();
      const properties = feature.properties as unknown as Omit<RouteSegmentDetail, "geometry">;
      const segment: RouteSegmentDetail = { ...properties, geometry: null };
      const geometry = feature.geometry as GeoJSON.Geometry | undefined;
      const lineCoordinates = geometry?.type === "LineString" ? (geometry.coordinates as [number, number][]) : [];
      const [snappedLng, snappedLat] =
        lineCoordinates.length > 0
          ? nearestPointOnLineString(lineCoordinates, [e.lngLat.lng, e.lngLat.lat])
          : [e.lngLat.lng, e.lngLat.lat];
      latest.current.onRouteSegmentSelect({ segment, latitude: snappedLat, longitude: snappedLng });
    }

    function handleMouseMove(e: MapMouseEvent) {
      const layers = latest.current.interactiveLayerIds.filter((id) => map.getLayer(id));
      if (layers.length === 0) {
        map.getCanvas().style.cursor = "";
        return;
      }
      const features = map.queryRenderedFeatures(e.point, { layers });
      map.getCanvas().style.cursor = features.length > 0 ? "pointer" : "";
    }

    // "load"は載っているすべてのタイルが揃った最初の描画で来る。アプリのソースは"load"の後に足す
    // （runWhenStyleReady）ので、この時点で描けているのは基礎地図だけ——覆いはここで外す。"idle"は
    // アプリのソースの取得まで待つので、遅い外部データが1つあると描けた地図を覆ったままになる。
    function handleLoad() {
      debugLog("map:lifecycle", "load（スタイル読み込み完了）");
      setStyleLoadFailed(false);
      setInitialTilesLoading(false);
    }
    function handleMapError(e: MapLibreErrorEvent) {
      const sourceId = (e as unknown as { sourceId?: string }).sourceId;
      // 有効なスタイルがまだ無いときの失敗は致命的（地図が白紙のまま）。それ以外の大半はタイル1枚の一過性の
      // 失敗で、次の取得で直るため警告にとどめる。
      const tagged = map as unknown as { __rcStyleReady?: boolean };
      const isFatal = !tagged.__rcStyleReady || styleReloadPendingRef.current;
      debugLog("map:error", e.error?.message ?? "unknown error", { sourceId }, isFatal ? "error" : "warn");
      if (isFatal) {
        setStyleLoadFailed(true);
        setInitialTilesLoading(false);
      }
      if (sourceId) markSourceErrored(sourceId);
    }
    function handleFirstIdle() {
      if (cancelled) return;
      recomputeLayerDataStatus();
      // 一度も動かさなくても、初期位置の範囲を取りに行けるよう伝える。
      reportViewport();
    }
    function handleTrackedSourceDataLoading(e: maplibregl.MapSourceDataEvent) {
      clearSourceLoading(e.sourceId);
    }
    function handleTrackedSourceData(e: maplibregl.MapSourceDataEvent) {
      notifySourceData(e.sourceId);
    }
    // 見えている範囲だけを取りに行くレイヤーへ、今の範囲を渡す（間引きは受け取る側）。
    function reportViewport() {
      const bounds = map.getBounds();
      if (!bounds) return;
      latest.current.look.onViewportChange({
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth(),
        zoom: map.getZoom(),
      });
    }
    function handleMoveEnd() {
      const bounds = map.getBounds();
      debugLog("map:viewport", "moveend", {
        zoom: Number(map.getZoom().toFixed(2)),
        bounds: bounds
          ? [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].map((n) => Number(n.toFixed(4)))
          : null,
      });
      settleViewport();
      reportViewport();
    }
    function handleZoomEnd() {
      debugLog("map:viewport", "zoomend", { zoom: Number(map.getZoom().toFixed(2)) });
      settleViewport();
      reportViewport();
    }
    // 動いている最中のresizeはmoveendを出さず"resize"だけを出す。範囲を渡さないと、広がった所が塗られない。
    function handleResize() {
      debugLog("map:viewport", "resize", { zoom: Number(map.getZoom().toFixed(2)) });
      settleViewport();
      reportViewport();
    }
    // 読み込み済みになった直後の一瞬は地物がまだ引けず、そこで数えると「空」に確定しうるため、"idle"でも数え直す。
    // "idle"では取得失敗を解除しない（settleViewportを呼ばない）——範囲が変わらなくても来るうえ、失敗したタイルも
    // 「読み込み済み」に数えられるため、続いている障害を「データなし」に化けさせる。
    function handleIdleRecompute() {
      recomputeLayerDataStatus();
    }

    map.on("click", handleClick);
    // ルートの線のハンドラは、レイヤーがまだ無い（ルート未生成）間に登録しても、MapLibreは発火しないだけで例外を
    // 出さない。
    const routeHitLayers = {
      segment: routeHitLayerId(latest.current.scene, ROUTE_HIT_TARGET_SEGMENT),
      spliceBand: routeHitLayerId(latest.current.scene, ROUTE_HIT_TARGET_SPLICE_BAND),
    };
    if (routeHitLayers.segment !== undefined) map.on("click", routeHitLayers.segment, handleRouteSegmentClick);
    if (routeHitLayers.spliceBand !== undefined) map.on("click", routeHitLayers.spliceBand, handleSpliceStretchClick);
    map.on("mousemove", handleMouseMove);
    map.on("load", handleLoad);
    map.on("error", handleMapError);
    map.on("moveend", handleMoveEnd);
    map.on("zoomend", handleZoomEnd);
    map.on("resize", handleResize);
    map.on("sourcedataloading", handleTrackedSourceDataLoading);
    map.on("sourcedata", handleTrackedSourceData);
    map.on("idle", handleIdleRecompute);
    map.once("idle", handleFirstIdle);
    const initialOverlayTimer = window.setTimeout(() => {
      if (!cancelled) setInitialTilesLoading(false);
    }, INITIAL_TILES_OVERLAY_MAX_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(initialOverlayTimer);
      resizeObserver.disconnect();
      map.off("styledata", collapseAttribution);
      map.off("sourcedata", collapseAttribution);
      map.off("click", handleClick);
      if (routeHitLayers.segment !== undefined) map.off("click", routeHitLayers.segment, handleRouteSegmentClick);
      if (routeHitLayers.spliceBand !== undefined)
        map.off("click", routeHitLayers.spliceBand, handleSpliceStretchClick);
      map.off("mousemove", handleMouseMove);
      map.off("load", handleLoad);
      map.off("error", handleMapError);
      map.off("moveend", handleMoveEnd);
      map.off("zoomend", handleZoomEnd);
      map.off("resize", handleResize);
      map.off("sourcedataloading", handleTrackedSourceDataLoading);
      map.off("sourcedata", handleTrackedSourceData);
      map.off("idle", handleIdleRecompute);
      map.remove();
      mapRef.current = null;
      // 印は破棄した地図に付いたままなので捨てる（Strict Modeの二重マウントで、残った印が新しい地図に付かない）。
      markerRef.current = null;
      appliedMarkerSourceRef.current = null;
      popupRef.current = null;
      waypointMarkersRef.current = [];
      destinationMarkerRef.current = null;
      selectedSegmentMarkerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 位置が変わったら地図と出発地点の印を更新する。印をドラッグで動かした先は「地点を置く」へ渡す。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyLocation = () => {
      if (skipNextFlyToRef.current) {
        skipNextFlyToRef.current = false;
      } else {
        map.flyTo({ center: [location.longitude, location.latitude], zoom: 13 });
      }

      if (markerRef.current && appliedMarkerSourceRef.current === locationSource) {
        markerRef.current.setLngLat([location.longitude, location.latitude]);
      } else {
        markerRef.current?.remove();
        const color = locationSource === "default" ? ORIGIN_MARK_FALLBACK_COLOR : ORIGIN_MARK_COLOR;
        markerRef.current = new maplibregl.Marker({
          element: createOriginMarkerElement(color),
          anchor: "center",
          draggable: latest.current.pointEditingEnabled,
        })
          .setLngLat([location.longitude, location.latitude])
          .addTo(map);
        markerRef.current.on("dragend", () => {
          const lngLat = markerRef.current!.getLngLat();
          skipNextFlyToRef.current = true;
          latest.current.onPinPlace("origin", { latitude: lngLat.lat, longitude: lngLat.lng });
        });
        appliedMarkerSourceRef.current = locationSource;
      }
    };

    runWhenStyleReady(map, applyLocation);
  }, [location, locationSource]);

  // 経由地の印（数件なので作り直す）。番号で通る順を示し、押すと消す（すぐ打ち直せるため確かめない）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyWaypointMarkers = () => {
      waypointMarkersRef.current.forEach((marker) => marker.remove());
      waypointMarkersRef.current = waypoints.map((point, index) => {
        const el = createPointMarkerElement("waypoint", String(index + 1));
        const marker = new maplibregl.Marker({ element: el, draggable: pointEditingEnabled })
          .setLngLat([point.longitude, point.latitude])
          .addTo(map);
        if (pointEditingEnabled) {
          marker.on("dragend", () => {
            const lngLat = marker.getLngLat();
            latest.current.onWaypointMove(index, { latitude: lngLat.lat, longitude: lngLat.lng });
          });
          bindDragAwareClick(marker, el, () => latest.current.onWaypointRemove(index));
        }
        return marker;
      });
    };

    runWhenStyleReady(map, applyWaypointMarkers);
  }, [waypoints, pointEditingEnabled]);

  // 出発地マーカーのつかめる/つかめないは、マーカーを作り直さずに切り替える——作り直す
  // effect（上）はカメラ移動を伴うため、パネルを切り替えるたびに地図が飛んでしまう。
  useEffect(() => {
    markerRef.current?.setDraggable(pointEditingEnabled);
  }, [pointEditingEnabled]);

  // 目的地の印。押すと解除する。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyDestinationMarker = () => {
      destinationMarkerRef.current?.remove();
      destinationMarkerRef.current = null;
      if (!destination) return;

      const el = createPointMarkerElement("destination");
      const marker = new maplibregl.Marker({ element: el, draggable: pointEditingEnabled })
        .setLngLat([destination.longitude, destination.latitude])
        .addTo(map);
      if (pointEditingEnabled) {
        marker.on("dragend", () => {
          const lngLat = marker.getLngLat();
          latest.current.onPinPlace("destination", { latitude: lngLat.lat, longitude: lngLat.lng });
        });
        bindDragAwareClick(marker, el, () => latest.current.onDestinationClear());
      }
      destinationMarkerRef.current = marker;
    };

    runWhenStyleReady(map, applyDestinationMarker);
  }, [destination, pointEditingEnabled]);

  // 選んでいる区間の印。選択が外れれば（どこで外しても）消える。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applySelectedSegmentMarker = () => {
      selectedSegmentMarkerRef.current?.remove();
      selectedSegmentMarkerRef.current = null;
      if (!selectedRouteSegment) return;

      const el = document.createElement("div");
      el.textContent = "📍";
      // touch-action:noneの理由は経由地マーカーと同じ。
      el.style.cssText =
        "font-size:26px; line-height:1; cursor:pointer; filter:drop-shadow(0 1px 2px rgba(0,0,0,0.5)); touch-action:none;";
      el.setAttribute("aria-label", "選択中の区間");
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        latest.current.onRouteSegmentSelect(null);
      });
      selectedSegmentMarkerRef.current = new maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([selectedRouteSegment.longitude, selectedRouteSegment.latitude])
        .addTo(map);
    };

    runWhenStyleReady(map, applySelectedSegmentMarker);
  }, [selectedRouteSegment]);

  // 地図に載るもの（面・道路の線・評価軸・点・気象・ルート）は、1つの scene として
  // 組み立てて1本の経路で当てる。**表示・絞り込み・重なり順はすべてここを通る。**
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyScene(map, scene);
    // 表示をONにしたレイヤーの状態をすぐ出す（タイルがキャッシュ済みだとsourcedataが来ない）。
    recomputeLayerDataStatus();
  }, [scene, recomputeLayerDataStatus]);

  // ルートを収めるのは候補の一覧が変わったときだけ（選び直すたびに収めると、利用者が動かした地図を打ち消す）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (routes.length > 0) {
      fitBoundsToRoutes(map, routes, latest.current.measureRouteFitObscuredPx?.());
    }
  }, [routes]);

  // 「地図の表示を再描画」: スタイルを取り直し、消えたレイヤーをいまの宣言から当て直す（押した人の地図だけ）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || look.refreshToken === 0) return;
    // 連打で取り直しを重ねない（新しい取り直しが前の読み込みを打ち切ると、当て直しが一度も走らない）。
    if (styleReloadPendingRef.current) return;
    styleReloadPendingRef.current = true;

    map.once("style.load", () => {
      styleReloadPendingRef.current = false;
      redrawFromCurrentProps(map);
    });
    // クエリでスタイルURLを変えることで、ブラウザのHTTPキャッシュではなく取り直しにする。
    resetBasemapAreaLayerPreparation(map);
    map.setStyle(`${mapStyleUrl()}?t=${Date.now()}`);
  }, [look.refreshToken, redrawFromCurrentProps]);

  // 道の詳細のポップアップ（MapLibreのPopupを器にする）。開いている間はその道を強調する（scene）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || roadPopup === null) return;
    const container = document.createElement("div");
    const popup = new maplibregl.Popup({ closeButton: true, maxWidth: "20rem" })
      .setLngLat(roadPopup.lngLat)
      .setDOMContent(container)
      .addTo(map);
    setRoadPopupContainer(container);
    // 中身が伸び縮みしたら（評価を取る・畳みを開く）、置く向きを決め直す。MapLibreは地図が動いたときにしか
    // 決め直さないので、開いた後に伸びた中身が画面の外へはみ出す。
    const resize =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => popup.setLngLat(popup.getLngLat()));
    resize?.observe(container);
    const close = () => setRoadPopup(null);
    popup.on("close", close);
    return () => {
      resize?.disconnect();
      popup.off("close", close);
      popup.remove();
      setRoadPopupContainer(null);
    };
  }, [roadPopup]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />
      {initialTilesLoading && !styleLoadFailed && (
        <div
          className="pointer-events-none absolute inset-0 z-5 flex flex-col items-center justify-center gap-2.5 bg-[var(--color-surface-2)]"
          aria-hidden="true"
        >
          <span className="size-7 animate-spin rounded-full border-3 border-[var(--color-border-strong)] border-t-[var(--color-accent)] motion-reduce:animate-none" />
          <span className={cn(textVariants({ variant: "hint" }), "text-[var(--color-muted-strong)]")}>
            地図を読み込み中…
          </span>
        </div>
      )}
      {styleLoadFailed && (
        <div
          role="alert"
          style={{
            position: "absolute",
            top: "1rem",
            left: "50%",
            transform: "translateX(-50%)",
            background: "var(--color-danger-muted)",
            color: "var(--color-danger)",
            border: "1px solid var(--color-danger)",
            borderRadius: "0.5rem",
            padding: "0.5rem 1rem",
            fontSize: "0.85rem",
            boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
            zIndex: 10,
            // 押せない表示なので地図へタッチを素通しする（ピンチの片方の指が乗るとページ全体のズームに化ける）。
            pointerEvents: "none",
          }}
        >
          地図の読み込みに失敗しました。しばらくしてから再読み込みしてください。
        </div>
      )}
      {roadPopup !== null &&
        roadPopupContainer !== null &&
        createPortal(
          <RoadInspectorPopup
            properties={roadPopup.properties}
            axes={catalog.axes}
            axisColors={catalog.axisColors}
            conditions={rideConditions != null ? { ...rideConditions, ...roadPopup.tile } : null}
            routePreference={routePreference}
          />,
          roadPopupContainer,
        )}
    </div>
  );
}

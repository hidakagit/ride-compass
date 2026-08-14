"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { ErrorEvent as MapLibreErrorEvent, GeoJSONSource, Map as MapLibreMap, Marker, MapMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Coordinates, RouteCandidate, RouteSegmentDetail } from "@/types/route";
import { ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM, refreshBasemapCache, roadSurfaceTileUrl } from "@/services/regionApi";
import { DEFAULT_ROAD_STYLE_MODE_ID, getRoadStyleMode, type RoadStyleModeId } from "@/components/Map/roadStyleModes";
import { getRouteStyleMode, type RouteStyleMode, type RouteStyleModeId } from "@/components/Map/routeStyleModes";
import { buildLegendFilterExpression } from "@/components/Map/legendFilter";
import { debugLog } from "@/lib/debugLog";

// 地図タイルはフロントエンド自身のオリジン（Next.jsのrewrites経由でバックエンドにプロキシ）
// から取得する。バックエンドAPI呼び出し（:8000）と同一オリジンにすると、大量のタイル
// リクエストがブラウザのオリジン単位の同時接続数上限を埋めてしまいAPI呼び出しが詰まる
// ことが実機確認で判明したため、あえてAPI_BASE_URLとは別オリジン（相対パス＝:3000）にしている。
const MAP_STYLE = "/api/basemap/styles/liberty";

// 国土地理院の色別標高図（ラスタタイル、APIキー不要）。地理院タイルはブラウザから直接
// 埋め込む利用を想定して公開されているため、基礎地図タイルとは異なりバックエンド経由の
// プロキシは行わない（別オリジンのため、基礎地図タイルとの接続数競合も発生しない）。
const GSI_RELIEF_TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png";
const GSI_RELIEF_MAX_ZOOM = 15;
const GSI_RELIEF_ATTRIBUTION =
  '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noreferrer">地理院タイル(色別標高図)</a>';

// 路面のベクタタイル内のレイヤー名。バックエンド（infrastructure/vector_tile.pyの
// ROAD_SURFACE_LAYER_NAME）と一致させる必要がある。
const ROAD_TILE_SOURCE_LAYER = "road_surface";

const ROUTES_SOURCE_ID = "route-candidates";
const ROUTES_LAYER_ID = "route-candidates-line";
const OUTLINE_SOURCE_ID = "route-selected-outline";
const OUTLINE_LAYER_ID = "route-selected-outline-line";
const DETAIL_SOURCE_ID = "route-detail-segments";
const DETAIL_LAYER_ID = "route-detail-segments-line";
const GSI_RELIEF_SOURCE_ID = "gsi-relief";
const GSI_RELIEF_LAYER_ID = "gsi-relief-raster";
const ROAD_TILE_SOURCE_ID = "region-road-surface-tiles";
const ROAD_TILE_LAYER_ID = "region-road-surface-tiles-line";

// routesToFeatureCollection/segmentsToFeatureCollection/computeRouteBoundsはexportして
// MapView.bench.ts（vitestのbench API）からGeoJSON構築のコストを直接計測できるようにしてある
// （ベンチマーク用途のみ。MapView自身は下のprivateなラッパー関数経由でしか呼ばない）。
export function routesToFeatureCollection(
  routes: RouteCandidate[],
  selectedRouteId: string | null
): GeoJSON.FeatureCollection<GeoJSON.LineString, { selected: boolean }> {
  // 選択中の候補が他の線に隠れないよう、配列の最後（最前面）に描画されるようにする
  const ordered = [...routes].sort((a, b) => Number(a.id === selectedRouteId) - Number(b.id === selectedRouteId));

  return {
    type: "FeatureCollection",
    features: ordered.map((route) => ({
      type: "Feature",
      properties: { selected: route.id === selectedRouteId },
      geometry: route.geometry,
    })),
  };
}

export function segmentsToFeatureCollection(
  segments: RouteSegmentDetail[]
): GeoJSON.FeatureCollection<GeoJSON.LineString, RouteSegmentDetail> {
  return {
    type: "FeatureCollection",
    features: segments.map((segment) => ({
      type: "Feature",
      properties: segment,
      geometry: {
        type: "LineString",
        coordinates: [
          [segment.start_longitude, segment.start_latitude],
          [segment.end_longitude, segment.end_latitude],
        ],
      },
    })),
  };
}

// 路面レイヤーの色分け式はモード定義（roadStyleModes.ts）、ルートレイヤー（風・勾配）の
// 色分け式はrouteStyleModes.tsから取得する。レイヤー作成時はデフォルトモードの式で作り、
// 以降のモード切替はsetPaintProperty/setFilterによる式の差し替えのみ（路面タイルには
// surface_good/surface/highwayが、ルートのsegmentsにはwind_difficulty/gradient_percentが
// すべて入っているため再取得は不要）。

function setLayerVisibility(map: MapLibreMap, layerId: string, visible: boolean) {
  if (!map.getLayer(layerId)) return;
  map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
}

// map.isStyleLoaded()はタイル読み込み中も一時的にfalseを返すため、
// それをガードに使うと「loadイベントは一度しか発火しない」性質と組み合わさって
// 二度目以降の描画が永久にスキップされることがある。スタイル自体が一度でも
// 読み込まれたかどうかだけをmapインスタンスに記録し、それを判定に使う。
function runWhenStyleReady(map: MapLibreMap, fn: () => void) {
  const tagged = map as unknown as { __rcStyleReady?: boolean };
  if (tagged.__rcStyleReady) {
    fn();
    return;
  }
  map.once("load", () => {
    tagged.__rcStyleReady = true;
    fn();
  });
}

function drawBaseRoutes(map: MapLibreMap, routes: RouteCandidate[], selectedRouteId: string | null) {
  const data = routesToFeatureCollection(routes, selectedRouteId);

  const applyData = () => {
    const source = map.getSource(ROUTES_SOURCE_ID) as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(ROUTES_SOURCE_ID, { type: "geojson", data });
    map.addLayer({
      id: ROUTES_LAYER_ID,
      type: "line",
      source: ROUTES_SOURCE_ID,
      paint: {
        // 未選択の候補もベースマップの道路色と紛れないよう、はっきりしたアンバー系にする
        "line-color": ["case", ["get", "selected"], "#2563eb", "#f59e0b"],
        "line-width": ["case", ["get", "selected"], 5, 3],
        "line-opacity": ["case", ["get", "selected"], 1, 0.85],
      },
    });
  };

  runWhenStyleReady(map, applyData);
}

// 選択中候補を常時識別できるよう、色分けレイヤーの下に薄いハローを敷く
function drawSelectedOutline(map: MapLibreMap, routes: RouteCandidate[], selectedRouteId: string | null) {
  const selected = routes.find((r) => r.id === selectedRouteId);
  const data: GeoJSON.FeatureCollection<GeoJSON.LineString> = {
    type: "FeatureCollection",
    features: selected ? [{ type: "Feature", properties: {}, geometry: selected.geometry }] : [],
  };

  const applyData = () => {
    const source = map.getSource(OUTLINE_SOURCE_ID) as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(OUTLINE_SOURCE_ID, { type: "geojson", data });
    map.addLayer(
      {
        id: OUTLINE_LAYER_ID,
        type: "line",
        source: OUTLINE_SOURCE_ID,
        paint: { "line-color": "#1e3a8a", "line-width": 10, "line-opacity": 0.25 },
      },
      map.getLayer(ROUTES_LAYER_ID) ? ROUTES_LAYER_ID : undefined
    );
  };

  runWhenStyleReady(map, applyData);
}

// ルートレイヤー（有向・選択中ルート基準のデータ。風・勾配）は、選択中候補にのみ
// 動的に重ね描きする。色分けモード・凡例フィルタの切替はスタイル式の差し替えのみ。
function drawDetailSegments(
  map: MapLibreMap,
  segments: RouteSegmentDetail[],
  mode: RouteStyleMode,
  hiddenLegendKeys: readonly string[]
) {
  const data = segmentsToFeatureCollection(segments);

  const applyData = () => {
    const source = map.getSource(DETAIL_SOURCE_ID) as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    } else {
      map.addSource(DETAIL_SOURCE_ID, { type: "geojson", data });
      map.addLayer({
        id: DETAIL_LAYER_ID,
        type: "line",
        source: DETAIL_SOURCE_ID,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        paint: { "line-color": mode.colorExpression as any, "line-width": 6, "line-opacity": 1 },
      });
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.setPaintProperty(DETAIL_LAYER_ID, "line-color", mode.colorExpression as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.setFilter(DETAIL_LAYER_ID, buildLegendFilterExpression(mode.legend, hiddenLegendKeys) as any);
    setLayerVisibility(map, DETAIL_LAYER_ID, true);
  };

  runWhenStyleReady(map, applyData);
}

function hideDetailSegments(map: MapLibreMap) {
  runWhenStyleReady(map, () => setLayerVisibility(map, DETAIL_LAYER_ID, false));
}

// 標高（国土地理院 色別標高図）・路面はどちらも「変わらないデータ」として、選択候補に
// 関係なく表示中の地図全体に重ね描きする。互いに排他ではなく同時にON/OFFできる。

// 標高ラスタは地図初期化時に一度だけソース/レイヤーを追加し（visibilityはデフォルトnone）、
// 以降はvisibilityの切替のみで表示・非表示する。他の重ね描きレイヤー（route/road）より
// 先に追加しておくことで、常にそれらの下（背景寄り）に描画されるようにしている。
function ensureGsiReliefLayer(map: MapLibreMap) {
  const applyData = () => {
    if (map.getSource(GSI_RELIEF_SOURCE_ID)) return;
    map.addSource(GSI_RELIEF_SOURCE_ID, {
      type: "raster",
      tiles: [GSI_RELIEF_TILE_URL],
      tileSize: 256,
      maxzoom: GSI_RELIEF_MAX_ZOOM,
      attribution: GSI_RELIEF_ATTRIBUTION,
    });
    map.addLayer({
      id: GSI_RELIEF_LAYER_ID,
      type: "raster",
      source: GSI_RELIEF_SOURCE_ID,
      paint: { "raster-opacity": 0.55 },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

function setGsiReliefVisibility(map: MapLibreMap, visible: boolean) {
  runWhenStyleReady(map, () => {
    ensureGsiReliefLayer(map);
    setLayerVisibility(map, GSI_RELIEF_LAYER_ID, visible);
  });
}

// 路面もGSI標高ラスタと同じ考え方で、地図初期化時に一度だけベクタタイルのソース/レイヤーを
// 追加し、以降はvisibilityの切替のみで表示・非表示する。標高ラスタの直後に追加することで、
// 標高の上・ルート系レイヤーの下に描画される。
function ensureRoadSurfaceTileLayer(map: MapLibreMap) {
  const applyData = () => {
    if (map.getSource(ROAD_TILE_SOURCE_ID)) return;
    map.addSource(ROAD_TILE_SOURCE_ID, {
      type: "vector",
      tiles: [roadSurfaceTileUrl()],
      minzoom: ROAD_TILE_MIN_ZOOM,
      maxzoom: ROAD_TILE_MAX_ZOOM,
    });
    map.addLayer({
      id: ROAD_TILE_LAYER_ID,
      type: "line",
      source: ROAD_TILE_SOURCE_ID,
      "source-layer": ROAD_TILE_SOURCE_LAYER,
      paint: {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "line-color": getRoadStyleMode(DEFAULT_ROAD_STYLE_MODE_ID).colorExpression as any,
        "line-width": 3,
        "line-opacity": 0.8,
      },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 路面レイヤーの表示状態を現在のモードに合わせて一括反映する。レイヤーは3つのモードで
// 共有するため色式を毎回差し替え、凡例で非表示にしたカテゴリはフィルタ式で除外する。
function applyRoadLayerState(
  map: MapLibreMap,
  showRoad: boolean,
  modeId: RoadStyleModeId,
  hiddenLegendKeys: readonly string[]
) {
  runWhenStyleReady(map, () => {
    ensureRoadSurfaceTileLayer(map);
    setLayerVisibility(map, ROAD_TILE_LAYER_ID, showRoad);
    const mode = getRoadStyleMode(modeId);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.setPaintProperty(ROAD_TILE_LAYER_ID, "line-color", mode.colorExpression as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.setFilter(ROAD_TILE_LAYER_ID, buildLegendFilterExpression(mode.legend, hiddenLegendKeys) as any);
  });
}

// 路面はvector sourceのminzoomにより、そのズームレベル未満ではタイルが要求・描画されない。
// 「表示範囲が広すぎます」の案内は、この閾値を現在のズームと比較して判定する
// （以前のbbox対角距離チェックの代わり。標高はラスタタイルのためこの判定の対象外）。
function updateRoadZoomHint(map: MapLibreMap, showRoad: boolean, onChange: (tooWide: boolean) => void) {
  onChange(showRoad && map.getZoom() < ROAD_TILE_MIN_ZOOM);
}

// 全候補のgeometryを包含するbounds計算そのものは地図インスタンスに依存しない純粋な処理
// のため、fitBoundsToRoutesから切り出してベンチマーク可能にしてある（MapView.bench.ts）。
export function computeRouteBounds(routes: RouteCandidate[]): maplibregl.LngLatBounds {
  const bounds = new maplibregl.LngLatBounds();
  for (const route of routes) {
    for (const [lng, lat] of route.geometry.coordinates) {
      bounds.extend([lng, lat]);
    }
  }
  return bounds;
}

function fitBoundsToRoutes(map: MapLibreMap, routes: RouteCandidate[]) {
  if (routes.length === 0) return;

  const bounds = computeRouteBounds(routes);

  runWhenStyleReady(map, () => map.fitBounds(bounds, { padding: 40 }));
}

function formatTime(iso: string | null): string {
  if (!iso) return "不明";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "不明";
  return date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

function formatWind(penalty: number | null): string {
  if (penalty == null) return "データなし";
  const label = penalty >= 0 ? "向かい風" : "追い風";
  return `${label} ${Math.abs(penalty).toFixed(1)} m/s`;
}

function formatRoad(good: boolean | null): string {
  if (good == null) return "不明";
  return good ? "舗装路" : "未舗装路";
}

function buildSegmentPopupHtml(segment: RouteSegmentDetail): string {
  const gradient = segment.gradient_percent != null ? `${segment.gradient_percent.toFixed(1)}%` : "不明";
  return `<div style="font-size:0.85rem; line-height:1.6;">
    <strong>${segment.cumulative_distance_km.toFixed(1)} km地点</strong>（到達予想 ${formatTime(segment.estimated_arrival_time)}）<br/>
    勾配: ${gradient}<br/>
    風: ${formatWind(segment.wind_penalty)}<br/>
    路面: ${formatRoad(segment.road_surface_good)}
  </div>`;
}

function buildRoadSurfacePopupHtml(properties: { surface_good: boolean | null }): string {
  return `<div style="font-size:0.85rem;">路面: ${formatRoad(properties.surface_good)}</div>`;
}

interface MapViewProps {
  routes: RouteCandidate[];
  selectedRouteId: string | null;
  location: Coordinates;
  showElevation: boolean;
  showRoad: boolean;
  roadStyleModeId: RoadStyleModeId;
  hiddenRoadLegendKeys: readonly string[];
  routeLayerOn: boolean;
  routeStyleModeId: RouteStyleModeId;
  hiddenRouteLegendKeys: readonly string[];
  onRegionZoomHintChange: (tooWide: boolean) => void;
  refreshToken: number;
}

export default function MapView({
  routes,
  selectedRouteId,
  location,
  showElevation,
  showRoad,
  roadStyleModeId,
  hiddenRoadLegendKeys,
  routeLayerOn,
  routeStyleModeId,
  hiddenRouteLegendKeys,
  onRegionZoomHintChange,
  refreshToken,
}: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  // 描画コールバックはmap.once("load", ...)頼み(runWhenStyleReady)だが、スタイルURL自体が
  // 404/5xx等で取得できない場合MapLibreは"load"ではなく"error"を発火するため、地図が
  // 無言で空白のまま永久に止まる問題があった。スタイルが一度もreadyにならないまま
  // errorが起きた場合はユーザーへ可視のメッセージを出す。
  const [styleLoadFailed, setStyleLoadFailed] = useState(false);
  const showRoadRef = useRef(showRoad);
  const onRegionZoomHintChangeRef = useRef(onRegionZoomHintChange);
  const redrawPropsRef = useRef({
    routes,
    selectedRouteId,
    routeLayerOn,
    routeStyleModeId,
    hiddenRouteLegendKeys,
    showElevation,
    showRoad,
    roadStyleModeId,
    hiddenRoadLegendKeys,
  });

  const selectedCandidate = routes.find((r) => r.id === selectedRouteId) ?? null;

  useEffect(() => {
    showRoadRef.current = showRoad;
  }, [showRoad]);

  useEffect(() => {
    onRegionZoomHintChangeRef.current = onRegionZoomHintChange;
  }, [onRegionZoomHintChange]);

  useEffect(() => {
    redrawPropsRef.current = {
      routes,
      selectedRouteId,
      routeLayerOn,
      routeStyleModeId,
      hiddenRouteLegendKeys,
      showElevation,
      showRoad,
      roadStyleModeId,
      hiddenRoadLegendKeys,
    };
  }, [
    routes,
    selectedRouteId,
    routeLayerOn,
    routeStyleModeId,
    hiddenRouteLegendKeys,
    showElevation,
    showRoad,
    roadStyleModeId,
    hiddenRoadLegendKeys,
  ]);

  // map.setStyle()は基礎地図タイルのキャッシュクリア後の再読み込みに使うが、これは
  // カスタムソース/レイヤーを含むスタイル全体を差し替えるため、こちらで追加した
  // ルート/ハロー/風/地域レイヤーがすべて消える。style.loadイベント後にこの関数で
  // 現在のprops（refで最新値を保持）から全レイヤーを作り直す。標高・路面はいずれも
  // タイルソースのため、再取得は不要（キャッシュがクリアされていれば次のタイル要求で
  // 自動的に新しいタイルが生成される）。
  const redrawAllLayers = useCallback((map: MapLibreMap) => {
    const {
      routes,
      selectedRouteId,
      routeLayerOn,
      routeStyleModeId,
      hiddenRouteLegendKeys,
      showElevation,
      showRoad,
      roadStyleModeId,
      hiddenRoadLegendKeys,
    } = redrawPropsRef.current;
    ensureGsiReliefLayer(map);
    setGsiReliefVisibility(map, showElevation);
    applyRoadLayerState(map, showRoad, roadStyleModeId, hiddenRoadLegendKeys);
    updateRoadZoomHint(map, showRoad, onRegionZoomHintChangeRef.current);

    drawBaseRoutes(map, routes, selectedRouteId);
    if (routes.length > 0) fitBoundsToRoutes(map, routes);
    drawSelectedOutline(map, routes, selectedRouteId);

    const selected = routes.find((r) => r.id === selectedRouteId) ?? null;
    if (routeLayerOn && selected?.segments) {
      drawDetailSegments(map, selected.segments, getRouteStyleMode(routeStyleModeId), hiddenRouteLegendKeys);
    } else {
      hideDetailSegments(map);
    }
  }, []);

  // 地図初期化
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE,
      center: [location.longitude, location.latitude],
      zoom: 13,
      // デバッグモード時、MapLibreが発行するリクエスト（スタイル/スプライト/グリフ/
      // 基礎地図タイル・路面タイルのTileJSON/実タイル）を種別ごとに逐一ログする。
      // debugLog()自体はデバッグモード無効時は即returnするため、常時attachして問題ない。
      transformRequest: (url, resourceType) => {
        debugLog("map:request", `${resourceType ?? "unknown"} ${url}`);
        return { url };
      },
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;
    debugLog("map:lifecycle", "初期化", { center: [location.longitude, location.latitude], zoom: 13 });
    // 標高ラスタ・路面ベクタタイルは他の重ね描きレイヤーより先に追加し、常に背景寄りに
    // 描画されるようにする（標高が最背面、その上に路面、さらに上にルート系レイヤー）
    ensureGsiReliefLayer(map);
    ensureRoadSurfaceTileLayer(map);

    // 路面レイヤーの区間・ルートレイヤーの詳細区間をクリックすると詳細をポップアップ表示する
    // （標高はラスタタイルのため、地物ごとのクリック判定は行わない）
    function handleClick(e: MapMouseEvent) {
      const layers = [DETAIL_LAYER_ID, ROAD_TILE_LAYER_ID].filter((id) => map.getLayer(id));
      if (layers.length === 0) return;
      const features = map.queryRenderedFeatures(e.point, { layers });
      if (features.length === 0) return;

      const feature = features[0];
      const html =
        feature.layer.id === DETAIL_LAYER_ID
          ? buildSegmentPopupHtml(feature.properties as unknown as RouteSegmentDetail)
          : buildRoadSurfacePopupHtml(feature.properties as unknown as { surface_good: boolean | null });

      popupRef.current?.remove();
      popupRef.current = new maplibregl.Popup({ closeButton: true }).setLngLat(e.lngLat).setHTML(html).addTo(map);
    }

    function handleMouseMove(e: MapMouseEvent) {
      const layers = [DETAIL_LAYER_ID, ROAD_TILE_LAYER_ID].filter((id) => map.getLayer(id));
      if (layers.length === 0) {
        map.getCanvas().style.cursor = "";
        return;
      }
      const features = map.queryRenderedFeatures(e.point, { layers });
      map.getCanvas().style.cursor = features.length > 0 ? "pointer" : "";
    }

    // 路面はベクタタイルのminzoom未満だと描画されないため、ズームのたびに現在のズームと
    // 閾値を比較して「表示範囲が広すぎます」の案内を更新する（データ取得は発生しない、
    // 単なる数値比較なので毎フレーム呼ばれても軽い）
    function handleZoom() {
      updateRoadZoomHint(map, showRoadRef.current, onRegionZoomHintChangeRef.current);
    }

    // マップの表示イベント（load完了・パン/ズーム確定・エラー）をデバッグログに記録する。
    // moveend/zoomendはスクロール・拡大縮小のたびに新しいviewport（＝新たなタイル要求の
    // 起点）が確定したタイミングを示す。
    function handleLoad() {
      debugLog("map:lifecycle", "load（スタイル読み込み完了）");
      setStyleLoadFailed(false);
    }
    function handleMapError(e: MapLibreErrorEvent) {
      const sourceId = (e as unknown as { sourceId?: string }).sourceId;
      debugLog("map:error", e.error?.message ?? "unknown error", { sourceId });
      // スタイル自体がまだ一度もreadyになっていない状態でのerrorは、個別タイルの一過性の
      // 失敗ではなくスタイル取得そのものの失敗である可能性が高い（runWhenStyleReadyが
      // 頼るmap.once("load", ...)がこの後発火しないままdrawBaseRoutes等の描画コールバックが
      // 永久にスキップされる）。デバッグモードに関わらずユーザーへ気づけるようにする。
      const tagged = map as unknown as { __rcStyleReady?: boolean };
      if (!tagged.__rcStyleReady) {
        setStyleLoadFailed(true);
      }
    }
    function handleMoveEnd() {
      const bounds = map.getBounds();
      debugLog("map:viewport", "moveend", {
        zoom: Number(map.getZoom().toFixed(2)),
        bounds: bounds
          ? [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].map((n) => Number(n.toFixed(4)))
          : null,
      });
    }
    function handleZoomEnd() {
      debugLog("map:viewport", "zoomend", { zoom: Number(map.getZoom().toFixed(2)) });
    }

    map.on("click", handleClick);
    map.on("mousemove", handleMouseMove);
    map.on("zoom", handleZoom);
    map.on("load", handleLoad);
    map.on("error", handleMapError);
    map.on("moveend", handleMoveEnd);
    map.on("zoomend", handleZoomEnd);

    return () => {
      map.off("click", handleClick);
      map.off("mousemove", handleMouseMove);
      map.off("zoom", handleZoom);
      map.off("load", handleLoad);
      map.off("error", handleMapError);
      map.off("moveend", handleMoveEnd);
      map.off("zoomend", handleZoomEnd);
      map.remove();
      mapRef.current = null;
      // markerRef/popupRefは破棄されたmapインスタンスに紐づいたままなのでリセットする。
      // リセットしないと、React Strict Modeの開発時二重マウント（mount→cleanup→mount）で
      // 1回目のmarkerが残ったまま2回目（実際に画面に残る方）のmapには一度も追加されず、
      // 以降locationが変わっても現在地マーカーが永久に表示されなくなる。
      markerRef.current = null;
      popupRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 位置が変わったら地図とマーカーを更新
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyLocation = () => {
      map.flyTo({ center: [location.longitude, location.latitude], zoom: 13 });

      if (markerRef.current) {
        markerRef.current.setLngLat([location.longitude, location.latitude]);
      } else {
        markerRef.current = new maplibregl.Marker({ color: "#e11d48" })
          .setLngLat([location.longitude, location.latitude])
          .addTo(map);
      }
    };

    runWhenStyleReady(map, applyLocation);
  }, [location]);

  // ルート候補のベース表示を更新（選択状態が変わったら選択色にも反映する）
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    drawBaseRoutes(map, routes, selectedRouteId);
  }, [routes, selectedRouteId]);

  // 表示範囲のフィットは「候補一覧が変わったとき」だけに限定する。
  // selectedRouteIdを依存に含めると、候補選択の切り替えのたびに（fitBoundsToRoutesは
  // routesしか使わず選択候補に寄せるわけでもないのに）地図が全候補の範囲へ強制的に
  // リセットされてしまい、ユーザーが選択後に手動でズーム/パンした操作を打ち消してしまう。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (routes.length > 0) {
      fitBoundsToRoutes(map, routes);
    }
  }, [routes]);

  // 選択中候補のハロー表示（レイヤーモードに関わらず常時）
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    drawSelectedOutline(map, routes, selectedRouteId);
  }, [routes, selectedRouteId]);

  // ルートレイヤー（有向データ: 風・勾配。選択中候補のみ）。ON/OFF・色分けモード・
  // 凡例フィルタのいずれの切替もスタイル式の差し替えだけで反映される
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (routeLayerOn && selectedCandidate?.segments) {
      drawDetailSegments(map, selectedCandidate.segments, getRouteStyleMode(routeStyleModeId), hiddenRouteLegendKeys);
    } else {
      hideDetailSegments(map);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routes, selectedRouteId, routeLayerOn, routeStyleModeId, hiddenRouteLegendKeys]);

  // 標高チェックの切替時は、ラスタレイヤーのvisibilityを切り替えるだけ（データ取得不要）
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    setGsiReliefVisibility(map, showElevation);
  }, [showElevation]);

  // 路面ON/OFF・色分けモード・凡例フィルタの切替は、いずれもvisibility/スタイル式/
  // フィルタ式の差し替えのみで反映される（データ取得はMapLibreがパン/ズームに応じて
  // 自動で行うため、明示的なfetchは不要）。マウント直後にも一度走り、localStorageから
  // 復元されたモードをデフォルト式で作られたレイヤーへ反映する。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyRoadLayerState(map, showRoad, roadStyleModeId, hiddenRoadLegendKeys);
    updateRoadZoomHint(map, showRoad, onRegionZoomHintChangeRef.current);
  }, [showRoad, roadStyleModeId, hiddenRoadLegendKeys]);

  // 「変わらないデータを更新」ボタン: 基礎地図タイル・路面ベクタタイルのキャッシュをクリアして
  // スタイルを再読み込みする。setStyle()はカスタムレイヤーを消すため、style.load後に
  // redrawAllLayersで全て描き直す（タイルソースは再取得不要。キャッシュがクリアされているため
  // 次のタイル要求で自動的に新しいタイルが生成される）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || refreshToken === 0) return;

    (async () => {
      try {
        await refreshBasemapCache();
        map.once("style.load", () => redrawAllLayers(map));
        map.setStyle(`${MAP_STYLE}?t=${Date.now()}`);
      } catch (error) {
        // refreshBasemapCacheは以前例外を投げない実装だったため、ここでのcatchが無くても
        // 問題なかったが、失敗を呼び出し元へ伝えるよう修正した結果、未処理のPromise
        // rejectionになるのを防ぐ必要がある。
        debugLog("map:error", `basemap refresh failed: ${error instanceof Error ? error.message : String(error)}`);
      }
    })();
  }, [refreshToken, redrawAllLayers]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />
      {styleLoadFailed && (
        <div
          role="alert"
          style={{
            position: "absolute",
            top: "1rem",
            left: "50%",
            transform: "translateX(-50%)",
            background: "#fef2f2",
            color: "#991b1b",
            border: "1px solid #fecaca",
            borderRadius: "0.5rem",
            padding: "0.5rem 1rem",
            fontSize: "0.85rem",
            boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
            zIndex: 10,
          }}
        >
          地図の読み込みに失敗しました。しばらくしてから再読み込みしてください。
        </div>
      )}
    </div>
  );
}

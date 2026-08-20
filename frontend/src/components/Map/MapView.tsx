"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { ErrorEvent as MapLibreErrorEvent, GeoJSONSource, Map as MapLibreMap, Marker, MapMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { omProtocol } from "@openmeteo/weather-map-layer";

// 風の矢印（改善計画T178）。om://プロトコルはMapLibreのプロトコル一覧という
// モジュールスコープの状態に登録するため、Reactのレンダーサイクルとは無関係に
// importされた時点で一度だけ登録すれば足りる（addProtocolは同名の再登録を
// 上書きするだけで副作用は無いため、Fast Refresh等でこのモジュールが再評価されても
// 実害は無い）。公式サンプル（examples/vector/wind-arrows.html）と同じ呼び方。
maplibregl.addProtocol("om", omProtocol);
import type {
  Coordinates,
  MotorVehicleDensityRecipeOverride,
  RoadSuitabilityRecipeOverride,
  RouteCandidate,
  RouteSegmentDetail,
  CarStressRecipeOverride,
} from "@/types/route";
import type { ExperimentSlot } from "@/types/experimentSlot";
import {
  ROAD_TILE_MAX_ZOOM,
  ROAD_TILE_MIN_ZOOM,
  accidentTileUrl,
  poiTileUrl,
  refreshBasemapCache,
  roadSurfaceTileUrl,
} from "@/services/regionApi";
import {
  CAR_STRESS_BREAKDOWN_BUTTON_ATTR,
  CAR_STRESS_BREAKDOWN_RESULT_ATTR,
  attachCarStressBreakdownHandler,
} from "@/components/Map/recipeBreakdownPopup";
import {
  buildAxisInspectorAffordanceHtml,
  attachAxisInspectorHandler,
} from "@/components/Map/axisInspectorPopup";
import {
  KNOWN_LINE_OPACITY,
  ROAD_FILTER_AXES,
  ROAD_LINE_COLOR_AXIS_ID,
  ROAD_LINE_WIDTH_AXIS_ID,
  ROAD_LINE_DASH_AXIS_ID,
  getRoadFilterAxis,
  type RoadFilterAxisId,
} from "@/components/Map/roadFilterAxes";
import { getRouteStyleMode, type RouteStyleMode, type RouteStyleModeId } from "@/components/Map/routeStyleModes";
import { buildCombinedLegendFilterExpression, buildLegendFilterExpression } from "@/components/Map/legendFilter";
import {
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_CAR_STRESS_RECIPE,
  buildCarStressExpression,
  evaluateCarStressLevel,
} from "@/components/Map/carStressExpression";
import {
  ACCIDENT_COLOR_EXPRESSION,
  ACCIDENT_RADIUS_EXPRESSION,
  BICYCLE_INFRA_COLOR_EXPRESSION,
  BICYCLE_INFRA_OPACITY_EXPRESSION,
  BICYCLE_INFRA_LABELS,
  DESIGNATION_COLOR_EXPRESSION,
  DESIGNATION_OPACITY_EXPRESSION,
  DESIGNATION_LABELS,
  STATIC_FILTER_AXES,
  STOP_POI_COLOR_EXPRESSION,
  STOP_POI_LABELS,
  SUPPLY_POI_COLOR_EXPRESSION,
  SUPPLY_POI_LABELS,
  CAR_STRESS_COLOR_EXPRESSION,
  buildCarStressColorExpression,
  buildCarStressLegend,
  type StaticFilterAxisId,
} from "@/components/Map/staticAttributeLayers";
import { ROAD_SURFACE_SHARED_LAYER_IDS, type LayerDataStatusByLayer, type MapLayerId } from "@/components/Map/mapLayers";
import {
  RAMP_AXES,
  axisLineLayerId,
  axisMapLayerId,
  buildAxisRampColorExpression,
  type RampAxis,
} from "@/components/Map/axisLayers";
import { useLayerDataStatus } from "@/components/Map/useLayerDataStatus";
import { debugLog } from "@/lib/debugLog";
import styles from "./MapView.module.css";

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
// ROAD_SURFACE_LAYER_NAME）と一致させる必要がある（改善計画T19: export_openapi.pyが
// 書き出すgenerated/region-tile-config.jsonとregionTileConfig.test.tsの照合テストが
// ドリフトを検知する。exportしているのはそのテストから参照するため）。
export const ROAD_TILE_SOURCE_LAYER = "road_surface";

// 事故レイヤー（外部静的データソース T50）のベクタタイル内のレイヤー名。バックエンド
// （infrastructure/vector_tile.pyのACCIDENT_LAYER_NAME）と一致させる（ROAD_TILE_SOURCE_LAYERと
// 同じドリフト検知の仕組み、region-tile-config.jsonのaccidentキー）。
export const ACCIDENT_TILE_SOURCE_LAYER = "accidents";

// 停止要因POIタイル（改善計画T54）内のレイヤー名。バックエンド
// （infrastructure/vector_tile.pyのSTOP_POI_LAYER_NAME）と一致させる必要がある
// （ROAD_TILE_SOURCE_LAYERと同じくregion-tile-config.json経由でドリフト検知、
// regionApi.test.ts参照）。同じpoi-tilesタイルにバックエンドは交差点密度（intersection）も
// 焼き込んでいるが、地図上の独立可視化レイヤーとしては提供しない判断をしたため
// （ルーティング材料のintersection_weightとしては引き続き使う。ユーザー判断:
// 道が何本交わっているかは道路網を見れば分かり、可視化としての追加情報が薄いため）
// フロント側では参照しない。
export const STOP_POI_SOURCE_LAYER = "stop_poi";

const ROUTES_SOURCE_ID = "route-candidates";
const ROUTES_LAYER_ID = "route-candidates-line";
const OUTLINE_SOURCE_ID = "route-selected-outline";
const OUTLINE_LAYER_ID = "route-selected-outline-line";
const DETAIL_SOURCE_ID = "route-detail-segments";
const DETAIL_LAYER_ID = "route-detail-segments-line";
const SLOTS_SOURCE_ID = "experiment-slots";
const SLOTS_LAYER_ID = "experiment-slots-line";
const GSI_RELIEF_SOURCE_ID = "gsi-relief";
const GSI_RELIEF_LAYER_ID = "gsi-relief-raster";
const PRECIPITATION_NOWCAST_SOURCE_ID = "region-precipitation-nowcast";
const PRECIPITATION_NOWCAST_LAYER_ID = "region-precipitation-nowcast-raster";
// 初期化時のsourceプレースホルダ（visibility:noneの間はMapLibreがタイルを要求しないため
// 実際にリクエストされることはない。applyPrecipitationNowcastStateが本物のURLへ
// setTilesで差し替える、ensureRoadSurfaceTileLayer等と同じ「仮の初期値」パターン）。
const PRECIPITATION_NOWCAST_PLACEHOLDER_TILE_URL =
  "https://www.jma.go.jp/bosai/jmatile/data/nowc/00000000000000/none/00000000000000/surf/hrpns/{z}/{x}/{y}.png";
const WIND_VECTOR_SOURCE_ID = "region-wind-vector";
const WIND_VECTOR_LAYER_ID = "region-wind-vector-arrows";
// 初期化時のsourceプレースホルダ（visibility:noneの間は矢印の実データを読みに行かない
// ため実際にはリクエストされない）。PRECIPITATION_NOWCAST_PLACEHOLDER_TILE_URLと同じ
// 「仮の初期値」パターン。time_step=valid_times_0固定でよい（applyWindVectorStateが
// 呼び出し直後に必ずsetUrlで実際のフレームへ差し替える）。
const WIND_VECTOR_PLACEHOLDER_SOURCE_URL =
  "om://https://openmeteo-data-spatial.b-cdn.net/jma_msm/latest.json?time_step=valid_times_0&variable=wind_u_component_10m&arrows=true";
const ROAD_TILE_SOURCE_ID = "region-road-surface-tiles";
const ROAD_TILE_LAYER_ID = "region-road-surface-tiles-line";
export const CAR_STRESS_LAYER_ID = "region-car-stress-line";
export const BICYCLE_INFRA_LAYER_ID = "region-bicycle-infra-line";
const DESIGNATION_LAYER_ID = "region-designation-line";
const ACCIDENT_TILE_SOURCE_ID = "region-accidents";
const ACCIDENT_LAYER_ID = "region-accidents-circle";
const POI_TILE_SOURCE_ID = "region-poi-tiles";
export const STOP_POI_LAYER_ID = "region-stop-poi-circle";
export const SUPPLY_POI_LAYER_ID = "region-supply-poi-circle";
// widthExpression/dashArrayExpressionは道路の種類軸にしか無い（roadFilterAxes.ts参照）ため
// 型上undefinedもありうるが、ROAD_LINE_WIDTH_AXIS_ID/ROAD_LINE_DASH_AXIS_IDが指す軸には
// 必ず設定されている。実行時に万一欠けていた場合、および「道路の種類」レイヤーがOFFの間の
// フォールバック（均一な太さ・実線）に使う。
const DEFAULT_ROAD_LINE_WIDTH = 3;
const DEFAULT_ROAD_LINE_DASHARRAY = [1, 0];
// ROAD_TILE_LAYER_IDの初期化直後の仮の不透明度、および路面の種類・道路の種類のどちらも
// opacityExpressionを持たない万一のフォールバック（実運用では両軸とも持つため通らない、
// applyRoadLayerState参照）。「路面の種類」がOFFで「道路の種類」だけONのときは、以前は
// 色が中立（ROAD_LINE_NEUTRAL_COLOR）でカテゴリを表さなかったためこの値に固定していたが、
// 道路の種類も専用の濃淡パレット・opacityExpressionを持つようになった（実機フィードバック
// 「道路種別が支配的な場合、色がすべて灰色で違和感がある」への対応）ため、現在は通常
// そちらが使われる。
const DEFAULT_ROAD_LINE_OPACITY = 0.8;
// road_surfaceの1次「素材」線レイヤー（道路種別/路面の合成ROAD_TILE_LAYER_ID・自転車
// インフラ・指定路線）は同じ道路ジオメトリ上に重なる独立レイヤーのため、複数を同時に
// ONにすると後から描画されたレイヤーが前のレイヤーを完全に覆い隠していた。実機
// フィードバック「1次要素をどれかOFFにして何が支配的なのか見たい」を受け、line-offsetで
// 道路と平行な複数トラックへ横並びに分離する（applyRoadMaterialTrackOffsets参照）。
// トラック間隔は当初line-width（3px）と揃え隙間なく境界を接する値にしていたが、全部ON時に
// 全体の帯が「地図の線が太すぎる」という実機フィードバックを受け、隣接トラックが
// line-widthの半分弱ずつ重なる値へ縮めた（重なりは色の切り替わりとして視認できる範囲に
// 収まり、完全な塗り潰しにはならない）。
const MATERIAL_TRACK_OFFSET_STEP = 2;
const ROAD_MATERIAL_TRACK_LAYER_IDS = [ROAD_TILE_LAYER_ID, BICYCLE_INFRA_LAYER_ID, DESIGNATION_LAYER_ID] as const;
// 改善計画（1次/2次の地図上表現の統一、松）: car_stress・ramp軸（停止密度・事故密度等、
// axisLayers.ts）は「推定」グループのメンバーで、いずれも同じroad_surfaceソース上の
// 独立レイヤーとして重ねて描画される。以前は1次（bicycleInfra/designation）と同じ
// 太さ・不透明度（3px・0.85）で塗っていたため、同時にONにすると後から追加された
// レイヤーが前のレイヤーを完全に覆い隠すだけで、材料（T167で連動ONする観測データ）と
// 推定の両方を同時に読み取れなかった（実機フィードバック「1次と2次の地図上表現を
// 一致させたい」）。2次は太く半透明な「下敷き」、1次は細くくっきりした「上書き」として
// 重ねることで、下に赤い区間があってもその上に事故地点の点や道路種別の線が乗って見える
// ようにする（描画順序はSTATIC_OVERLAY_LAYERS参照。1次より下・road_surfaceより上に置く）。
// 幅は1次「素材」線が全部ONになったときの最大帯幅（トラック数×オフセット間隔＋自身の
// 太さ）から計算する。以前はこの値を手計算した結果（「3本・オフセット2px・幅3pxなら
// 7px」）を別のマジックナンバーとしてここへ直書きしており、オフセット間隔や素材の本数
// （ROAD_MATERIAL_TRACK_LAYER_IDSの要素数）を変えるとここだけ追従せず、下敷きが帯の外側に
// はみ出す／内側に収まらないというズレを黙って再発させていた（実機フィードバック「オフセット、
// カーシングの幅は重ねる線が3本から変わっても揃うようにして」「なるべくベタで書かず、揃える
// 制約があるものは連動させて欲しい」への対応）。この式にすることで、以後は上記2定数の変更に
// 自動で追従する。
const SECONDARY_AXIS_CASING_WIDTH =
  (ROAD_MATERIAL_TRACK_LAYER_IDS.length - 1) * MATERIAL_TRACK_OFFSET_STEP + DEFAULT_ROAD_LINE_WIDTH;
const SECONDARY_AXIS_CASING_OPACITY = 0.45;
// ROAD_TILE_LAYER_IDの初期化直後の仮の色（applyRoadLayerStateが呼び出し直後に必ず実際の
// 値へ上書きする、placeholder的な役割のみ）。実際に「路面の種類OFF・道路の種類ON」時の
// 色分けはroadFilterAxes.tsのHIGHWAY_GROUPS（濃淡パレット、COLOR_HIGHWAY_*）を使う
// （以前はここへ固定した中立グレーを使っていたが、「不明・他」と同じ色を全区間に塗って
// しまい「道路種別が支配的な場合、色がすべて灰色で違和感がある」という実機フィードバックを
// 受けて廃止した。applyRoadLayerState参照）。
const ROAD_LINE_NEUTRAL_COLOR = "#9ca3af";

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

// 区間featureのproperties型。形状はfeature.geometry側に持たせるため、propertiesからは
// geometryを除外する（クリック時のポップアップ表示に必要な値だけを残す）。
export type RouteSegmentProperties = Omit<RouteSegmentDetail, "geometry">;

export function segmentsToFeatureCollection(
  segments: RouteSegmentDetail[]
): GeoJSON.FeatureCollection<GeoJSON.LineString, RouteSegmentProperties> {
  return {
    type: "FeatureCollection",
    features: segments.map((segment) => {
      const { geometry, ...properties } = segment;
      return {
        type: "Feature",
        properties,
        // 区間の道なり形状（backendがルートgeometryから切り出した部分列）をそのまま使う。
        // geometryが無い場合（古いレスポンス・2点未満のEdge等）のみ、従来どおり
        // 始点・終点を結ぶ直線で代替する（カーブ区間では道路から外れる近似表示）。
        geometry: geometry ?? {
          type: "LineString",
          coordinates: [
            [segment.start_longitude, segment.start_latitude],
            [segment.end_longitude, segment.end_latitude],
          ],
        },
      };
    }),
  };
}

// 路面レイヤーの色分け式は常に固定（roadFilterAxes.tsのROAD_LINE_COLOR_AXIS_ID）、
// ルートレイヤー（風・勾配）の色分け式はモード定義（routeStyleModes.ts）から取得する。
// ルート側は以降のモード切替もsetPaintProperty/setFilterによる式の差し替えのみ（路面タイルには
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
        // 未選択の候補は「背景の参考線」として見えればよく、選択中候補
        // （特にroute-detail-segments-lineの路面/難易度色分け）を主役として引き立てる
        // 脇役にする（以前はアンバー・幅3・不透明度0.85で選択中候補と競合し輻輳して
        // 見づらかった。ユーザーFB「区間が荒すぎて実態がよくわからない」の後続改善）。
        // 色はアンバーだとOpenFreeMapベースマップの主要道路（暖色系のオレンジ〜ベージュ）に
        // 溶け込んで見分けが付きにくかったため、ベースマップに存在しない寒色（スレート）へ
        // 変更した。8候補比較（地図上での見比べ）自体は維持したいため、消えるほど薄くは
        // せず（実機確認で不透明度0.45は背景に埋没して見えなくなることを確認済み）、
        // 「はっきり見えるが選択中候補ほどは目立たない」不透明度に調整している。
        "line-color": ["case", ["get", "selected"], "#2563eb", "#64748b"],
        "line-width": ["case", ["get", "selected"], 5, 2.5],
        "line-opacity": ["case", ["get", "selected"], 1, 0.65],
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

// 実験スロット（研究インターフェース改善 §10-3）の重ね描き。各スロットの代表候補
// （topCandidate、生成直後のtotal_score最上位で固定）の全体形状をスロット別の色で描く
// （「路面重視にしたら形が変わったか」等の比較が本命）。detail-segments（現在選択中の
// 色分け表示）より下・base routes（8候補の参考線）より上に置くため、作成時にDETAIL_LAYER_IDの
// 直下（既に存在すれば）を明示指定する（drawSelectedOutlineと同じ考え方）。
function drawExperimentSlots(map: MapLibreMap, slots: ExperimentSlot[]) {
  const data: GeoJSON.FeatureCollection<GeoJSON.LineString, { color: string }> = {
    type: "FeatureCollection",
    features: slots.map((slot) => ({
      type: "Feature",
      properties: { color: slot.color },
      geometry: slot.topCandidate.geometry,
    })),
  };

  const applyData = () => {
    const source = map.getSource(SLOTS_SOURCE_ID) as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource(SLOTS_SOURCE_ID, { type: "geojson", data });
    map.addLayer(
      {
        id: SLOTS_LAYER_ID,
        type: "line",
        source: SLOTS_SOURCE_ID,
        paint: {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          "line-color": ["get", "color"] as any,
          "line-width": 4,
          "line-opacity": 0.85,
        },
      },
      map.getLayer(DETAIL_LAYER_ID) ? DETAIL_LAYER_ID : undefined
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

// 気象庁 降水ナウキャスト（改善計画T170/T171）。GSI標高ラスタと同じ「初期化時に一度だけ
// ソース/レイヤーを追加し、以降はvisibility/タイルURLの差し替えのみ」のパターンだが、
// タイルURL自体が対象時刻（地図上の時刻スライダー）によって変わる点がGSI標高と異なる
// （GSIは常に同じURLテンプレート）。地図の最前面（他の全レイヤーより後に追加）に置き、
// 雨雲が道路網の上に重なって見えるようにする。
function ensurePrecipitationNowcastLayer(map: MapLibreMap) {
  const applyData = () => {
    if (map.getSource(PRECIPITATION_NOWCAST_SOURCE_ID)) return;
    map.addSource(PRECIPITATION_NOWCAST_SOURCE_ID, {
      type: "raster",
      tiles: [PRECIPITATION_NOWCAST_PLACEHOLDER_TILE_URL],
      tileSize: 256,
      minzoom: 4,
      maxzoom: 10,
      attribution: "気象庁",
    });
    map.addLayer({
      id: PRECIPITATION_NOWCAST_LAYER_ID,
      type: "raster",
      source: PRECIPITATION_NOWCAST_SOURCE_ID,
      paint: { "raster-opacity": 0.65 },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// タイルURL（page.tsx側でprecipitationNowcast.tsのnowcastTileUrlTemplateから計算した値）を
// 反映する。visible/tileUrlのどちらか一方でも欠けていれば非表示のまま
// （フェッチ未完了・取得失敗時に古いURLのタイルが一瞬見えるのを防ぐ）。
function applyPrecipitationNowcastState(map: MapLibreMap, visible: boolean, tileUrl: string | undefined) {
  runWhenStyleReady(map, () => {
    ensurePrecipitationNowcastLayer(map);
    if (tileUrl) {
      const source = map.getSource(PRECIPITATION_NOWCAST_SOURCE_ID) as maplibregl.RasterTileSource | undefined;
      source?.setTiles([tileUrl]);
    }
    setLayerVisibility(map, PRECIPITATION_NOWCAST_LAYER_ID, visible && tileUrl != null);
  });
}

// 風の矢印（改善計画T178）。JMA MSM由来・Open-Meteo配信（`@openmeteo/weather-map-layer`の
// om://プロトコル）。降水ナウキャストと同じ「初期化時に一度だけソース/レイヤーを追加し、
// 以降はvisibility/URLの差し替えのみ」のパターンだが、om://ソースはtiles配列ではなく
// url1本（time_step等のクエリを丸ごと含む）で時刻を表すため、タイル差し替えは
// setTiles(タイルURLテンプレート)ではなくsetUrl(ソースURL全体)を使う点が異なる。ライブラリの
// vector source仕様（対応方針参照、公式サンプルexamples/vector/wind-arrows.html）では
// ラスタ（背景色分け）も併用できるが本タスクでは矢印のみを描画する（地図の視界を圧迫しない、
// 設計原則12。ラスタは対応方針上「任意」）。降水ナウキャストの直後（最前面寄り）に追加し、
// 雨雲の上に矢印が重なって見えるようにする。
function ensureWindVectorLayer(map: MapLibreMap) {
  const applyData = () => {
    if (map.getSource(WIND_VECTOR_SOURCE_ID)) return;
    map.addSource(WIND_VECTOR_SOURCE_ID, {
      type: "vector",
      url: WIND_VECTOR_PLACEHOLDER_SOURCE_URL,
      attribution: "気象庁の予測に基づく（Open-Meteo経由）",
    });
    map.addLayer({
      id: WIND_VECTOR_LAYER_ID,
      type: "line",
      source: WIND_VECTOR_SOURCE_ID,
      "source-layer": "wind-arrows",
      paint: {
        // 風速値（valueプロパティ）が強いほど濃く表示する（公式サンプルと同じ段階分け）。
        "line-color": [
          "case",
          ["boolean", [">", ["to-number", ["get", "value"]], 5], false],
          "rgba(30, 64, 175, 0.7)",
          ["boolean", [">", ["to-number", ["get", "value"]], 3], false],
          "rgba(30, 64, 175, 0.55)",
          "rgba(30, 64, 175, 0.4)",
        ],
        // 矢印の長さはライブラリ側のベクトルタイル形状に焼き込まれておりズームレベルの
        // グリッド間隔で決まる（実機確認: 風速0.27〜7.0 m/sの範囲でも長さはほぼ一定だった）。
        // 太さ（paint、こちら側で自由に設定できる）で強さを表現する。ユーザー要望「1m/s単位で
        // 把握したい」を受け、0-15 m/s（穏やか〜強風、ロードバイクで支障が出始める目安）を
        // 傾き0.5px/(m/s)固定の直線で補間する2点指定にした（中間点を挟むと区間ごとに傾きが
        // 変わり「1m/s＝何px」が一定でなくなるため、2点のみのシンプルな直線にする）。
        // 15 m/s超は9pxで頭打ち（MapLibre interpolateは範囲外を両端の値でクランプする）。
        "line-width": [
          "interpolate",
          ["linear"],
          ["to-number", ["get", "value"]],
          0, 1.5,
          15, 9,
        ],
      },
      layout: { "line-cap": "round", visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// sourceUrl（page.tsx側でwindLayer.tsのwindVectorSourceUrlから計算した値）を反映する。
// visible/sourceUrlのどちらか一方でも欠けていれば非表示のまま（applyPrecipitationNowcastState
// と同じ、フェッチ未完了・取得失敗時に古いフレームの矢印が一瞬見えるのを防ぐ）。
function applyWindVectorState(map: MapLibreMap, visible: boolean, sourceUrl: string | undefined) {
  runWhenStyleReady(map, () => {
    ensureWindVectorLayer(map);
    if (sourceUrl) {
      const source = map.getSource(WIND_VECTOR_SOURCE_ID) as maplibregl.VectorTileSource | undefined;
      source?.setUrl(sourceUrl);
    }
    setLayerVisibility(map, WIND_VECTOR_LAYER_ID, visible && sourceUrl != null);
  });
}

// 路面もGSI標高ラスタと同じ考え方で、地図初期化時に一度だけベクタタイルのソース/レイヤーを
// 追加し、以降はvisibilityの切替・setPaintProperty/setFilterのみで表示・非表示・見た目を
// 変える。標高ラスタの直後に追加することで、標高の上・ルート系レイヤーの下に描画される。
// paintの初期値は仮の中立値（applyRoadLayerStateが呼び出し直後に必ず実際の値へ上書きする、
// 改善計画T165参照）。
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
        "line-color": ROAD_LINE_NEUTRAL_COLOR,
        "line-width": DEFAULT_ROAD_LINE_WIDTH,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "line-dasharray": DEFAULT_ROAD_LINE_DASHARRAY as any,
        "line-opacity": DEFAULT_ROAD_LINE_OPACITY,
        // 初期値は0（applyRoadMaterialTrackOffsetsが可視化のたびに実際の値へ上書きする）
        "line-offset": 0,
      },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 路面レイヤーの表示状態を一括反映する（改善計画T165: 「道路情報」を「路面の種類」
// （roadSurface、色）・「道路の種類」（roadType、太さ・線種）の論理2レイヤーへ分割。
// 物理的には同じ道路ジオメトリへ線レイヤーを2枚重ねると上が下を塗り潰し「色×太さ」の
// 多重表現が壊れるため、1本のMapLibre線レイヤー（ROAD_TILE_LAYER_ID）へ動的に合成する）。
// - 両方ON: 色=路面の種類の配色、太さ・線種=道路の種類（従来どおりの見た目）
// - 路面の種類のみON: 色=路面の種類の配色、太さ・線種は中立（均一・実線）
// - 道路の種類のみON: 色=道路の種類の濃淡パレット（COLOR_HIGHWAY_*、太さと同じ序列）、
//   太さ・線種=道路の種類（改善計画: 実機フィードバック「道路種別が支配的な場合、色が
//   すべて灰色で違和感がある」への対応。以前は色を一律ROAD_LINE_NEUTRAL_COLORにしていた）
// - 両方OFF: レイヤー自体を隠す
// フィルタも表示中の軸だけを反映する（OFF中の軸のhiddenKeysで絞り込むと、その軸を
// OFFにしているのに地物が消える、という矛盾が起きるため）。
function applyRoadLayerState(
  map: MapLibreMap,
  showRoadSurface: boolean,
  showRoadType: boolean,
  hiddenKeysByAxis: Record<RoadFilterAxisId, readonly string[]>
) {
  runWhenStyleReady(map, () => {
    ensureRoadSurfaceTileLayer(map);
    const showAny = showRoadSurface || showRoadType;
    setLayerVisibility(map, ROAD_TILE_LAYER_ID, showAny);
    if (showAny) {
      // 色・不透明度は「路面の種類」がONなら常にそちらの式を優先し（太さ・線種と違い、
      // 色チャンネルは1つしか持てないため両方ONでも路面側が勝つ）、OFFの間だけ道路の種類
      // 側の濃淡パレット（roadFilterAxes.ts: COLOR_HIGHWAY_*）を使う。
      const colorExpression = showRoadSurface
        ? getRoadFilterAxis(ROAD_LINE_COLOR_AXIS_ID).colorExpression
        : getRoadFilterAxis(ROAD_LINE_WIDTH_AXIS_ID).colorExpression;
      const widthExpression = showRoadType
        ? (getRoadFilterAxis(ROAD_LINE_WIDTH_AXIS_ID).widthExpression ?? DEFAULT_ROAD_LINE_WIDTH)
        : DEFAULT_ROAD_LINE_WIDTH;
      const dashArrayExpression = showRoadType
        ? (getRoadFilterAxis(ROAD_LINE_DASH_AXIS_ID).dashArrayExpression ?? DEFAULT_ROAD_LINE_DASHARRAY)
        : DEFAULT_ROAD_LINE_DASHARRAY;
      const opacityExpression = showRoadSurface
        ? (getRoadFilterAxis(ROAD_LINE_COLOR_AXIS_ID).opacityExpression ?? DEFAULT_ROAD_LINE_OPACITY)
        : (getRoadFilterAxis(ROAD_LINE_WIDTH_AXIS_ID).opacityExpression ?? DEFAULT_ROAD_LINE_OPACITY);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map.setPaintProperty(ROAD_TILE_LAYER_ID, "line-color", colorExpression as any);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map.setPaintProperty(ROAD_TILE_LAYER_ID, "line-width", widthExpression as any);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map.setPaintProperty(ROAD_TILE_LAYER_ID, "line-dasharray", dashArrayExpression as any);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map.setPaintProperty(ROAD_TILE_LAYER_ID, "line-opacity", opacityExpression as any);
    }
    const activeAxes = ROAD_FILTER_AXES.filter((axis) =>
      axis.id === ROAD_LINE_COLOR_AXIS_ID ? showRoadSurface : showRoadType
    );
    const combinedFilter = buildCombinedLegendFilterExpression(
      activeAxes.map((axis) => ({ legend: axis.legend, hiddenKeys: hiddenKeysByAxis[axis.id] ?? [] }))
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.setFilter(ROAD_TILE_LAYER_ID, combinedFilter as any);
  });
}

// road_surfaceの1次「素材」線レイヤー（道路種別/路面の合成ROAD_TILE_LAYER_ID・自転車
// インフラ・指定路線）を並列トラックへ分離するオフセット計算。定数
// （MATERIAL_TRACK_OFFSET_STEP/ROAD_MATERIAL_TRACK_LAYER_IDS）・下敷き幅との連動理由は
// 上部のDEFAULT_ROAD_LINE_WIDTH直後のコメント参照。
// 現在ONの素材レイヤー集合から各レイヤーのline-offsetを計算して適用する。ON中のものだけを
// 対称に割り付ける（1件→0、2件→±1.5、3件→-3/0/+3）ため、どれかをOFFにすると残りが
// 自動で中央（実際の道路の位置）へ寄り直す。OFF中のレイヤーもoffsetを0へ戻しておき、
// 次にONにしたときに古いオフセット値が一瞬残らないようにする。
function applyRoadMaterialTrackOffsets(
  map: MapLibreMap,
  visible: { road: boolean; bicycleInfra: boolean; designation: boolean }
) {
  runWhenStyleReady(map, () => {
    const visibleByLayerId: Record<string, boolean> = {
      [ROAD_TILE_LAYER_ID]: visible.road,
      [BICYCLE_INFRA_LAYER_ID]: visible.bicycleInfra,
      [DESIGNATION_LAYER_ID]: visible.designation,
    };
    const onLayerIds = ROAD_MATERIAL_TRACK_LAYER_IDS.filter((layerId) => visibleByLayerId[layerId]);
    const center = (onLayerIds.length - 1) / 2;
    for (const layerId of ROAD_MATERIAL_TRACK_LAYER_IDS) {
      if (!map.getLayer(layerId)) continue;
      const onIndex = onLayerIds.indexOf(layerId);
      const offset = onIndex === -1 ? 0 : (onIndex - center) * MATERIAL_TRACK_OFFSET_STEP;
      map.setPaintProperty(layerId, "line-offset", offset);
    }
  });
}

// 車ストレス・自転車インフラ（静的道路属性P0、docs/static-road-attributes-plan.md）は
// 路面と同じベクタソース（タイルに新規プロパティが焼き込まれている）を再利用した
// 独立レイヤー。色分け軸は路面のように選択式ではなく固定（staticAttributeLayers.ts）で、
// 絞り込みUIも持たない（P0時点では色分け表示のみ）。ensureRoadSurfaceTileLayerと同じ
// パターンで初期化時に一度だけ追加し、以降はvisibilityの切替のみで表示・非表示する。
function ensureCarStressLayer(map: MapLibreMap) {
  const applyData = () => {
    if (map.getLayer(CAR_STRESS_LAYER_ID)) return;
    map.addLayer({
      id: CAR_STRESS_LAYER_ID,
      type: "line",
      source: ROAD_TILE_SOURCE_ID,
      "source-layer": ROAD_TILE_SOURCE_LAYER,
      paint: {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "line-color": CAR_STRESS_COLOR_EXPRESSION as any,
        "line-width": SECONDARY_AXIS_CASING_WIDTH,
        "line-opacity": SECONDARY_AXIS_CASING_OPACITY,
      },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 車ストレスレシピ（研究モードで上書き可能、改善計画: 車ストレスレシピ調整UIパネル）を
// レイヤーへ反映する。ensureCarStressLayerは常に既定レシピの色で作成する（STATIC_OVERLAY_
// LAYERSの他エントリと同じ`(map) => void`の形を保つため）ため、この関数を同じ呼び出し元
// （setStaticOverlayFiltersの直後）で常にセットで呼び、上書き中なら実際のレシピの色へ補正する。
// レイヤーが未作成（一度も表示ONにされていない）ならensure側に任せ何もしない。
// 注意: レイヤーの初回作成はこの関数だけでなくsetStaticOverlayVisibility（別useEffect、
// layer.ensure経由）からも起こりうる。両者は別々のeffectだが、マウント直後は両方とも
// 初回に一度ずつ実行され、setStaticOverlayFiltersの呼び出し（本関数を含む）がその中で
// 完了するため、実際に既定色のままレイヤーが可視化される瞬間は生じない
// （MapView.overlayFilters.test.ts等では検証していない、コード上の実行順序に基づく前提）。
function applyCarStressRecipe(map: MapLibreMap, recipe: CarStressRecipeOverride, levelExpression?: unknown[]) {
  runWhenStyleReady(map, () => {
    if (!map.getLayer(CAR_STRESS_LAYER_ID)) return;
    const colorExpression = buildCarStressColorExpression(recipe, levelExpression);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.setPaintProperty(CAR_STRESS_LAYER_ID, "line-color", colorExpression as any);
  });
}

function ensureBicycleInfraLayer(map: MapLibreMap) {
  const applyData = () => {
    if (map.getLayer(BICYCLE_INFRA_LAYER_ID)) return;
    map.addLayer({
      id: BICYCLE_INFRA_LAYER_ID,
      type: "line",
      source: ROAD_TILE_SOURCE_ID,
      "source-layer": ROAD_TILE_SOURCE_LAYER,
      paint: {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "line-color": BICYCLE_INFRA_COLOR_EXPRESSION as any,
        "line-width": 3,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "line-opacity": BICYCLE_INFRA_OPACITY_EXPRESSION as any,
        // 初期値は0（applyRoadMaterialTrackOffsetsが可視化のたびに実際の値へ上書きする）
        "line-offset": 0,
      },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 指定路線（外部静的データソース T51、KSJ N10/N12）。車ストレス・自転車インフラと同じく
// 路面と同じベクタソースを再利用する独立レイヤー。designationプロパティは該当区間のみ
// 値を持つ（未該当はプロパティ欠落、DESIGNATION_COLOR_EXPRESSIONのcoalesceで灰色に倒す）。
function ensureDesignationLayer(map: MapLibreMap) {
  const applyData = () => {
    if (map.getLayer(DESIGNATION_LAYER_ID)) return;
    map.addLayer({
      id: DESIGNATION_LAYER_ID,
      type: "line",
      source: ROAD_TILE_SOURCE_ID,
      "source-layer": ROAD_TILE_SOURCE_LAYER,
      paint: {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "line-color": DESIGNATION_COLOR_EXPRESSION as any,
        "line-width": 3,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "line-opacity": DESIGNATION_OPACITY_EXPRESSION as any,
        // 初期値は0（applyRoadMaterialTrackOffsetsが可視化のたびに実際の値へ上書きする）
        "line-offset": 0,
      },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 事故レイヤー（外部静的データソース T50）。road_surfaceとは独立のベクタソース・タイル
// エンドポイント（PBF取込範囲とは無関係に取込済みの警察庁データそのもの）のため、
// ensureRoadSurfaceTileLayerと同じ「初期化時に一度だけ追加、以降はvisibility切替のみ」の
// パターンだがソース自体を新規に持つ。円の色は自転車関連/その他（involves_bicycle）、
// 大きさは死亡事故（fatal）の強調に使う（staticAttributeLayers.ts参照）。
function ensureAccidentTileLayer(map: MapLibreMap) {
  const applyData = () => {
    if (map.getSource(ACCIDENT_TILE_SOURCE_ID)) return;
    map.addSource(ACCIDENT_TILE_SOURCE_ID, {
      type: "vector",
      tiles: [accidentTileUrl()],
      minzoom: ROAD_TILE_MIN_ZOOM,
      maxzoom: ROAD_TILE_MAX_ZOOM,
    });
    map.addLayer({
      id: ACCIDENT_LAYER_ID,
      type: "circle",
      source: ACCIDENT_TILE_SOURCE_ID,
      "source-layer": ACCIDENT_TILE_SOURCE_LAYER,
      paint: {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "circle-color": ACCIDENT_COLOR_EXPRESSION as any,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "circle-radius": ACCIDENT_RADIUS_EXPRESSION as any,
        "circle-opacity": 0.75,
        "circle-stroke-width": 1,
        "circle-stroke-color": "#ffffff",
      },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 停止要因POI・交差点密度（改善計画T54）は点データのため、路面・車ストレス・自転車
// インフラとは別の新規ベクタソース（region-poi-tiles）を使う。ズーム範囲は路面と同じ
// （regionApi.ts: ROAD_TILE_MIN_ZOOM/MAX_ZOOM、backend側もT54で同じ範囲に準拠）。
function ensurePoiTileSource(map: MapLibreMap) {
  if (map.getSource(POI_TILE_SOURCE_ID)) return;
  map.addSource(POI_TILE_SOURCE_ID, {
    type: "vector",
    tiles: [poiTileUrl()],
    minzoom: ROAD_TILE_MIN_ZOOM,
    maxzoom: ROAD_TILE_MAX_ZOOM,
  });
}

function ensureStopPoiLayer(map: MapLibreMap) {
  const applyData = () => {
    ensurePoiTileSource(map);
    if (map.getLayer(STOP_POI_LAYER_ID)) return;
    map.addLayer({
      id: STOP_POI_LAYER_ID,
      type: "circle",
      source: POI_TILE_SOURCE_ID,
      "source-layer": STOP_POI_SOURCE_LAYER,
      paint: {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "circle-color": STOP_POI_COLOR_EXPRESSION as any,
        "circle-radius": 4,
        "circle-stroke-width": 1,
        "circle-stroke-color": "#ffffff",
        "circle-opacity": 0.9,
      },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 補給・休憩ポイントPOI（改善計画T101）。停止要因POIと同じregion-poi-tiles
// （source-layer: stop_poi）を共有する独立レイヤー。バックエンドのMVT SQLはkindを
// 無条件で焼き込むため、この時点（addLayer）ではfilterを付けない。実際のkind値による
// 絞り込みはsetStaticOverlayFilters側のbaseFilter（STATIC_FILTER_AXES: supplyPoi）が
// 常時ANDで適用する（同じ仕組みでstopPoi側もsupplyPoiのkindを除外している）。
function ensureSupplyPoiLayer(map: MapLibreMap) {
  const applyData = () => {
    ensurePoiTileSource(map);
    if (map.getLayer(SUPPLY_POI_LAYER_ID)) return;
    map.addLayer({
      id: SUPPLY_POI_LAYER_ID,
      type: "circle",
      source: POI_TILE_SOURCE_ID,
      "source-layer": STOP_POI_SOURCE_LAYER,
      paint: {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "circle-color": SUPPLY_POI_COLOR_EXPRESSION as any,
        "circle-radius": 4,
        "circle-stroke-width": 1,
        "circle-stroke-color": "#ffffff",
        "circle-opacity": 0.9,
      },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 「変わらないデータ」系オーバーレイのうち、路面（フィルタ式も併せ持つため別扱い）を除く
// 6レイヤー（標高・車ストレス・自転車インフラ・指定路線・事故・停止要因POI）は、
// いずれも「初期化時にensureで一度だけ追加、以降はvisibilityの切替のみ」という同型の
// 生存期間を持つ。各レイヤーの見た目（addLayerの中身）は上のensure*Layer関数に残しつつ、
// 「どのpropsフラグがどのensure関数・layerIdに対応するか」の対応表だけをここに集約する
// （改善計画T47 R-6: 静的レイヤーが+2種類に達した時点でのensure/setペアの宣言的ループ化）。
// 二次軸の汎用rampレイヤー（改善計画T145b）。axis-catalog.json（backendレジストリ生成物）の
// kind="ramp"軸ごとに、road_surfaceタイルへ焼き込み済みの事実プロパティ（per-km密度）を
// カタログ宣言のしきい値で色分けする線レイヤーを自動生成する。ensure関数は既存の
// ensureCarStressLayer等と同じ「初期化時に一度だけ追加、以降はvisibility切替のみ」パターン。
function makeEnsureAxisRampLayer(axis: RampAxis): (map: MapLibreMap) => void {
  return (map: MapLibreMap) => {
    runWhenStyleReady(map, () => {
      const layerId = axisLineLayerId(axis.axisId);
      if (map.getLayer(layerId)) return;
      map.addLayer({
        id: layerId,
        type: "line",
        source: ROAD_TILE_SOURCE_ID,
        "source-layer": ROAD_TILE_SOURCE_LAYER,
        paint: {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          "line-color": buildAxisRampColorExpression(axis) as any,
          "line-width": SECONDARY_AXIS_CASING_WIDTH,
          "line-opacity": SECONDARY_AXIS_CASING_OPACITY,
        },
        layout: { visibility: "none" },
      });
    });
  };
}

const AXIS_OVERLAY_LAYERS = RAMP_AXES.map((axis) => ({
  key: axisMapLayerId(axis.axisId) as string,
  layerId: axisLineLayerId(axis.axisId),
  ensure: makeEnsureAxisRampLayer(axis),
}));

// 改善計画（1次/2次の地図上表現の統一、松）: map.addLayer()はbeforeId省略時にレイヤー
// スタックの最上位へ積み上げるため、この配列の並び順がそのままensureAllStaticOverlayLayers
// （下記）でのensure()呼び出し順＝実際の描画の重なり順（先＝背面、後＝前面）になる。
// carStress・ramp軸（推定/composite、SECONDARY_AXIS_CASING_WIDTH/OPACITYの太く半透明な
// 下敷き）をroad_surface本体の直上へまとめ、bicycleInfra・designation・accidents・
// stopPoi・supplyPoi（観測/raw、通常の太さ・不透明度のくっきりした上書き）をその上に置く。
// 以前はramp軸が配列末尾（最前面）だったため、材料の連動ON（T167）で観測データと推定を
// 同時に表示しても、後から追加された推定側が観測データを塗り潰して見えなくなっていた。
const STATIC_OVERLAY_LAYERS: readonly { key: string; layerId: string; ensure: (map: MapLibreMap) => void }[] = [
  { key: "elevation", layerId: GSI_RELIEF_LAYER_ID, ensure: ensureGsiReliefLayer },
  { key: "carStress", layerId: CAR_STRESS_LAYER_ID, ensure: ensureCarStressLayer },
  ...AXIS_OVERLAY_LAYERS,
  { key: "bicycleInfra", layerId: BICYCLE_INFRA_LAYER_ID, ensure: ensureBicycleInfraLayer },
  { key: "designation", layerId: DESIGNATION_LAYER_ID, ensure: ensureDesignationLayer },
  { key: "accidents", layerId: ACCIDENT_LAYER_ID, ensure: ensureAccidentTileLayer },
  { key: "stopPoi", layerId: STOP_POI_LAYER_ID, ensure: ensureStopPoiLayer },
  { key: "supplyPoi", layerId: SUPPLY_POI_LAYER_ID, ensure: ensureSupplyPoiLayer },
];

// 2次（carStress・ramp軸）のうち、下敷き（SECONDARY_AXIS_CASING_WIDTH/OPACITY）の対象。
// STATIC_OVERLAY_LAYERSと同じ並び（carStress→ramp軸）から取り出すだけの薄いラッパー。
const SECONDARY_AXIS_CASING_TARGETS: readonly { key: string; layerId: string }[] = [
  { key: "carStress", layerId: CAR_STRESS_LAYER_ID },
  ...AXIS_OVERLAY_LAYERS,
];

// 改善計画（2次の下敷きの副作用対応）: 2次（carStress・ramp軸）を太く半透明な下敷きに
// するのは、その材料（1次）が同時に表示されているときだけにする。材料が1つも表示されて
// いなければ下に隠すものが無いため、通常の太さ・不透明度（1次と同じ、DEFAULT_ROAD_LINE_
// WIDTH/KNOWN_LINE_OPACITY）に戻す。以前はcarStress・ramp軸をONにした瞬間から常に
// 太く半透明にしていたため、道路網が密な都市部では下敷きの重なりだけで地図全体が
// ぼやけて見えてしまっていた（実機フィードバック）。casingLayerKeysは、どの2次レイヤーの
// 材料が現在表示中かをpage.tsx側（axisMaterialLayerIds）が判定して渡す（このファイルは
// レイヤー固有の材料関係を知らない汎用描画係のまま、という方針を保つ）。
function applySecondaryAxisCasingStyles(map: MapLibreMap, casingLayerKeys: ReadonlySet<string>) {
  runWhenStyleReady(map, () => {
    for (const target of SECONDARY_AXIS_CASING_TARGETS) {
      if (!map.getLayer(target.layerId)) continue;
      const useCasing = casingLayerKeys.has(target.key);
      map.setPaintProperty(target.layerId, "line-width", useCasing ? SECONDARY_AXIS_CASING_WIDTH : DEFAULT_ROAD_LINE_WIDTH);
      map.setPaintProperty(
        target.layerId,
        "line-opacity",
        useCasing ? SECONDARY_AXIS_CASING_OPACITY : KNOWN_LINE_OPACITY
      );
    }
  });
}

type StaticOverlayKey = string;

// レイヤーごとのデータ取得状態（改善計画T87）の算出元となる(source, source-layer)対応表。
// roadType/roadSurface（T165で「道路情報」から論理分割）/carStress/bicycleInfra/
// designationは同じroad_surfaceタイルを再利用しているため（T59でroad_edgesが未構築の
// 地点では、この5レイヤーが同時にempty/errorになるのが正しい挙動）、あえて同じ
// sourceId/sourceLayerを指す。elevationは国土地理院のラスタタイルで
// source-layerを持たないため、取得失敗のみ検知しempty判定はしない。routeは自前データ
// （選択中候補のgeometryをそのままGeoJSON化するのみ）のためこの表の対象外。
// MapView.segments.test.tsと同じ考え方で、computeLayerDataStatusのテスト
// （MapView.dataStatus.test.ts）から個別レイヤーのsourceIdを参照できるようexportしている。
export const LAYER_DATA_SOURCES: readonly { key: MapLayerId; sourceId: string; sourceLayer?: string }[] = [
  { key: "roadType", sourceId: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
  { key: "roadSurface", sourceId: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
  { key: "carStress", sourceId: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
  { key: "bicycleInfra", sourceId: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
  { key: "designation", sourceId: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
  { key: "accidents", sourceId: ACCIDENT_TILE_SOURCE_ID, sourceLayer: ACCIDENT_TILE_SOURCE_LAYER },
  { key: "stopPoi", sourceId: POI_TILE_SOURCE_ID, sourceLayer: STOP_POI_SOURCE_LAYER },
  { key: "supplyPoi", sourceId: POI_TILE_SOURCE_ID, sourceLayer: STOP_POI_SOURCE_LAYER },
  { key: "elevation", sourceId: GSI_RELIEF_SOURCE_ID },
  // 降水ナウキャスト（T171）。ラスタタイルのためelevationと同じくsourceLayer無し
  // （取得失敗のみ検知対象、0件相当の「empty」判定はしない）。
  { key: "precipitationNowcast", sourceId: PRECIPITATION_NOWCAST_SOURCE_ID },
  // 風の矢印（T178）。vector sourceだがsource-layerを指定するとquerySourceFeaturesの
  // 0件判定（empty）が働いてしまう。風は連続場（地球上のどの地点にも値がある）のため
  // 「0件」という状態自体が意味を持たず、precipitationNowcastと同じく取得失敗のみを
  // 検知対象とする（あえてsourceLayerを指定しない）。
  { key: "windVector", sourceId: WIND_VECTOR_SOURCE_ID },
  // 二次軸rampレイヤー（T145b）はroad_surfaceタイルへ焼き込み済みのプロパティを読む
  // （carStress等と同じソース共有。ROAD_SURFACE_SHARED_LAYER_IDSにも登録済み）
  ...RAMP_AXES.map((axis) => ({
    key: axisMapLayerId(axis.axisId) as MapLayerId,
    sourceId: ROAD_TILE_SOURCE_ID,
    sourceLayer: ROAD_TILE_SOURCE_LAYER,
  })),
];

// レイヤーデータ状態（loading/empty/error、改善計画T87）の算出・追跡（computeLayerDataStatus・
// clearStaleTrackedSourceErrors・状態管理）はuseLayerDataStatus.ts（改善計画T123）に
// 集約されている。LAYER_DATA_SOURCES自体はSTATIC_OVERLAY_LAYERS等の他の定数と同じくこの
// ファイルに残し、フックへ引数として渡す（フック側からMapView.tsxを逆importしないため）。

// クリック判定・カーソル変更（handleClick/handleMouseMove）の対象レイヤー一覧。
// STATIC_OVERLAY_LAYERSからelevation（ラスタタイルのため地物クリック判定が効かない）を
// 除いたものに、STATIC_OVERLAY_LAYERSの対象外であるDETAIL_LAYER_ID（ルート詳細区間）・
// ROAD_TILE_LAYER_ID（路面）を加える（改善計画T83）。以前はhandleClick/handleMouseMoveの
// 2箇所に同一の8要素配列を手書きしており、STATIC_OVERLAY_LAYERSと合わせて三重管理
// だった。レイヤー追加時に片方だけ追記漏れすると「ポップアップは出るがカーソルが
// 変わらない」等の非対称な劣化が検知されず残る。
// 二次軸rampレイヤー（T145b）はクリック時の内訳ポップアップ（recipeBreakdownPopup等）に
// 対応する専用表示を持たないため、elevationと同様にクリック判定から除外する
// （一次属性→軸スコアを遡る汎用インスペクタは改善計画T146のスコープ）。
const INTERACTIVE_LAYER_IDS = [
  DETAIL_LAYER_ID,
  ROAD_TILE_LAYER_ID,
  ...STATIC_OVERLAY_LAYERS.filter(
    (layer) => layer.key !== "elevation" && !layer.key.startsWith("axis:"),
  ).map((layer) => layer.layerId),
];

function ensureAllStaticOverlayLayers(map: MapLibreMap) {
  for (const layer of STATIC_OVERLAY_LAYERS) layer.ensure(map);
}

function setStaticOverlayVisibility(map: MapLibreMap, flags: Record<StaticOverlayKey, boolean>) {
  runWhenStyleReady(map, () => {
    for (const layer of STATIC_OVERLAY_LAYERS) {
      layer.ensure(map);
      setLayerVisibility(map, layer.layerId, flags[layer.key]);
    }
  });
}

// 改善計画T63: 標高を除く6レイヤー（車ストレス・自転車インフラ・指定路線・事故・
// 停止要因POI・補給休憩POI[T101]）の絞り込み。STATIC_FILTER_AXES（staticAttributeLayers.ts）の
// layerIdでSTATIC_OVERLAY_LAYERSのkeyと突き合わせ、そのレイヤーが持つ軸ぶん（事故のみ2軸、
// 他は1軸）を道路情報と同じbuildCombinedLegendFilterExpressionでAND束ねする。軸を持たない
// 標高はスキップする（setFilterはvector/circleレイヤー用でラスタレイヤーには使えないため）。
//
// carStress軸だけは、レシピ上書き中（改善計画: 車ストレスレシピ調整UIパネル）は
// STATIC_FILTER_AXESの静的なlegend（既定レシピ由来）ではなく、現在のレシピから
// buildCarStressLegendで都度組み立てたlegendを使う。レベルの意味（どのフィーチャーが
// 「2」に該当するか）がレシピ次第で変わるため、絞り込みチェックボックスの表示（ラベル・色）は
// 不変のまま、フィルタの実体だけがレシピに追従する。
// MapView.overlayFilters.test.tsからフェイクmapで検証できるようexportしている
// （computeLayerDataStatus等と同じ方針）。
export function setStaticOverlayFilters(
  map: MapLibreMap,
  hiddenKeysByAxis: Record<StaticFilterAxisId, readonly string[]>,
  carStressRecipe: CarStressRecipeOverride,
  roadSuitabilityRecipe: RoadSuitabilityRecipeOverride,
  motorVehicleDensityRecipe: MotorVehicleDensityRecipeOverride,
) {
  runWhenStyleReady(map, () => {
    // buildCarStressLegend/buildCarStressColorExpressionはどちらも内部でレシピから
    // 同じレベル判定式を組み立てるため、この呼び出し内で1回だけ計算して両方へ渡す
    // （setFilter/setPaintPropertyというMapLibre側の実処理に対し無視できるコストとはいえ、
    // 同一の式木を毎回2回組み立てる必要はないため）。roadSuitabilityRecipe/
    // motorVehicleDensityRecipeは車ストレスが参照する「車との近さ」(N2)の材料
    // （改善計画: 車との近さ材料の共有元化）。
    const carStressLevelExpression = buildCarStressExpression(
      carStressRecipe,
      roadSuitabilityRecipe,
      motorVehicleDensityRecipe,
    );
    for (const layer of STATIC_OVERLAY_LAYERS) {
      const axes = STATIC_FILTER_AXES.filter((axis) => axis.layerId === layer.key);
      if (axes.length === 0) continue;
      layer.ensure(map);
      const filter = buildCombinedLegendFilterExpression(
        axes.map((axis) => ({
          legend:
            axis.axisId === "carStress"
              ? buildCarStressLegend(carStressRecipe, carStressLevelExpression)
              : axis.legend,
          hiddenKeys: hiddenKeysByAxis[axis.axisId] ?? [],
          baseFilter: axis.baseFilter,
        }))
      );
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map.setFilter(layer.layerId, filter as any);
    }
    applyCarStressRecipe(map, carStressRecipe, carStressLevelExpression);
  });
}

// road_surfaceタイルを共有する4レイヤー（mapLayers.ts: ROAD_SURFACE_SHARED_LAYER_IDS）の
// いずれかが表示ONかを判定する。road_surfaceソースを参照する箇所（ズーム範囲外判定・
// レイヤーデータ状態表示の抑制）が両方ともこのヘルパー経由でROAD_SURFACE_SHARED_LAYER_IDSを
// 参照するようにし、「4レイヤーのどれが対象か」を1箇所（mapLayers.ts）だけが知っていれば
// よい状態にする（改善計画T87レビュー指摘: 以前はroadの表示状態だけを見ていたため、
// road自体はOFFのままcarStress等だけONの場合にズーム範囲外の案内が一切出なかった）。
// MapView.segments.test.tsと同じ考え方でテスト可能にexportしている。
export function isRoadSurfaceGroupVisible(visibility: Partial<Record<MapLayerId, boolean>>): boolean {
  return ROAD_SURFACE_SHARED_LAYER_IDS.some((id) => visibility[id]);
}

// 路面はvector sourceのminzoomにより、そのズームレベル未満ではタイルが要求・描画されない。
// 「表示範囲が広すぎます」の案内は、この閾値を現在のズームと比較して判定する
// （以前のbbox対角距離チェックの代わり。標高はラスタタイルのためこの判定の対象外）。
// showRoadSurfaceGroupは isRoadSurfaceGroupVisible の結果（road_surfaceタイルを共有する
// 4レイヤーのいずれかが表示ONか）。以前はroadの表示状態だけを見ていたため、road自体はOFFの
// ままcarStress等だけONで同じソースを見ている場合にこの案内が一切出ない不整合があった
// （改善計画T87レビュー指摘）。
function updateRoadZoomHint(
  map: MapLibreMap,
  showRoadSurfaceGroup: boolean,
  onChange: (tooWide: boolean) => void
) {
  onChange(showRoadSurfaceGroup && map.getZoom() < ROAD_TILE_MIN_ZOOM);
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

// ポップアップ本文の共通スタイル。line-heightは以前1.6だったが、短い行の羅列に対して
// 間延びして見えたため、サイドバーの他カード（page.module.css .legendCard等）に近い
// 密度の1.4へ詰めた。
const POPUP_BODY_STYLE = "font-size:var(--font-size-md); line-height:1.4;";

function buildSegmentPopupHtml(segment: RouteSegmentProperties): string {
  const gradient = segment.gradient_percent != null ? `${segment.gradient_percent.toFixed(1)}%` : "不明";
  return `<div style="${POPUP_BODY_STYLE}">
    <strong>${segment.cumulative_distance_km.toFixed(1)} km地点</strong>[到達予想 ${formatTime(segment.estimated_arrival_time)}]<br/>
    勾配: ${gradient}<br/>
    風: ${formatWind(segment.wind_penalty)}<br/>
    路面: ${formatRoad(segment.road_surface_good)}
  </div>`;
}

// 静的道路属性P0（docs/static-road-attributes-plan.md）で追加したプロパティ。
// タグ・算出不能はundefined/null（MVTのST_AsMVTがNULLプロパティを省略するため、
// 実際にはキー自体が存在しない）。
interface RoadSurfacePopupProperties {
  /** 車ストレスの区間別判定内訳（改善計画T90）を引き直すための識別子。 */
  osm_way_id?: number | null;
  surface_good?: boolean | null;
  smoothness?: string | null;
  tunnel?: boolean | null;
  bridge?: boolean | null;
  car_stress?: number | null;
  bicycle_infra?: string | null;
  /** 指定路線コンフレーション機構（外部静的データソース T51）。未該当はプロパティ欠落。 */
  designation?: string | null;
}

const SMOOTHNESS_LABELS: Record<string, string> = {
  excellent: "非常に良い",
  good: "良い",
  intermediate: "普通",
  bad: "悪い",
  very_bad: "非常に悪い",
  horrible: "劣悪",
  very_horrible: "劣悪",
  impassable: "通行不能",
};

// 車ストレスの区間別判定内訳（改善計画T90）。ポップアップ内のボタン・結果表示先を
// 識別するdata属性・配線ロジックはrecipeBreakdownPopup.ts（改善計画T123）に集約されている
// （HTML文字列としてMapLibreのPopup#setHTMLへ渡すため、Reactのイベントハンドラは使えず、
// addTo後にDOMを直接querySelectorして配線する）。

function buildRoadSurfacePopupHtml(properties: RoadSurfacePopupProperties): string {
  const rows = [`路面: ${formatRoad(properties.surface_good ?? null)}`];
  if (properties.smoothness) {
    rows.push(`路面状態: ${SMOOTHNESS_LABELS[properties.smoothness] ?? properties.smoothness}`);
  }
  if (properties.bicycle_infra) {
    rows.push(`自転車インフラ: ${BICYCLE_INFRA_LABELS[properties.bicycle_infra] ?? properties.bicycle_infra}`);
  }
  if (properties.car_stress != null) {
    rows.push(`車の圧迫感: ${properties.car_stress}/5`);
  }
  if (properties.designation) {
    rows.push(DESIGNATION_LABELS[properties.designation] ?? properties.designation);
  }
  if (properties.tunnel) rows.push("トンネル");
  if (properties.bridge) rows.push("橋・高架");
  const carStressBreakdownAffordance =
    properties.car_stress != null
      ? `<div style="margin-top:var(--space-1);">
          <button type="button" ${CAR_STRESS_BREAKDOWN_BUTTON_ATTR} style="font:inherit; font-size:var(--font-size-sm); padding:2px 8px; cursor:pointer;">車の圧迫感の内訳を見る</button>
          <div ${CAR_STRESS_BREAKDOWN_RESULT_ATTR}></div>
        </div>`
      : "";
  // 区間インスペクタ（改善計画T146）: 一次属性→全二次軸→合成コスト(参考値)。osm_way_idが
  // 分かる区間なら常に出す（車ストレス個別ボタンと違い特定軸の判定可否に依存しない）。
  const axisInspectorAffordance = properties.osm_way_id != null ? buildAxisInspectorAffordanceHtml() : "";
  return `<div style="${POPUP_BODY_STYLE}">${rows.join("<br/>")}${carStressBreakdownAffordance}${axisInspectorAffordance}</div>`;
}

// 外部静的データソース T50（警察庁交通事故統計）のクリックポップアップ用プロパティ。
interface AccidentPopupProperties {
  fatal?: boolean | null;
  involves_bicycle?: boolean | null;
  occurred_year?: number | null;
}

function buildAccidentPopupHtml(properties: AccidentPopupProperties): string {
  const rows = [properties.involves_bicycle ? "自転車関連事故" : "事故[自転車以外]"];
  if (properties.fatal) rows.push("死亡事故");
  if (properties.occurred_year != null) rows.push(`発生年: ${properties.occurred_year}`);
  return `<div style="${POPUP_BODY_STYLE}">${rows.join("<br/>")}</div>`;
}

// 改善計画T54: 停止要因POIのクリックポップアップ用プロパティ。
interface StopPoiPopupProperties {
  kind?: string | null;
}

function buildStopPoiPopupHtml(properties: StopPoiPopupProperties): string {
  const label = properties.kind ? (STOP_POI_LABELS[properties.kind] ?? properties.kind) : "不明";
  return `<div style="${POPUP_BODY_STYLE}">停止要因: ${label}</div>`;
}

// 改善計画T101: 補給・休憩ポイントPOIのクリックポップアップ用プロパティ（StopPoiPopupPropertiesと同じ形）。
interface SupplyPoiPopupProperties {
  kind?: string | null;
}

function buildSupplyPoiPopupHtml(properties: SupplyPoiPopupProperties): string {
  const label = properties.kind ? (SUPPLY_POI_LABELS[properties.kind] ?? properties.kind) : "不明";
  return `<div style="${POPUP_BODY_STYLE}">補給・休憩: ${label}</div>`;
}

interface MapViewProps {
  routes: RouteCandidate[];
  selectedRouteId: string | null;
  location: Coordinates;
  showElevation: boolean;
  /** 降水ナウキャスト（改善計画T170/T171）。ONの間、precipitationNowcastTileUrl
   * （page.tsx側でprecipitationNowcast.tsから計算した現在時刻スライダー位置のタイルURL）を
   * 反映する。tileUrlが未定（フェッチ未完了・取得失敗）の間はONでも非表示のまま。 */
  showPrecipitationNowcast: boolean;
  precipitationNowcastTileUrl: string | undefined;
  /** 風の矢印（改善計画T178）。ONの間、windVectorTileUrl（page.tsx側でwindLayer.tsの
   * windVectorSourceUrlから計算した現在時刻スライダー位置のom://ソースURL）を反映する。
   * showPrecipitationNowcast/precipitationNowcastTileUrlと同じ扱い。 */
  showWindVector: boolean;
  windVectorTileUrl: string | undefined;
  /** 道路の種類（改善計画T165で「道路情報」から論理分割）。太さ・線種で反映する。
   * 物理描画はshowRoadSurfaceと同じMapLibre線レイヤーへ合成される（MapView.tsx:
   * applyRoadLayerState参照）。 */
  showRoadType: boolean;
  /** 路面の種類（改善計画T165で「道路情報」から論理分割）。色で反映する。 */
  showRoadSurface: boolean;
  /** 車ストレス・自転車インフラ（静的道路属性P0）。路面と同じソースを再利用する独立レイヤー。 */
  showCarStress: boolean;
  showBicycleInfra: boolean;
  /** 車ストレスレシピの上書き（研究モード、改善計画: 車ストレスレシピ調整UIパネル）。
   * undefinedなら既定レシピ（DEFAULT_CAR_STRESS_RECIPE）を使う。地図の色分け・凡例による
   * 絞り込み・区間クリックの内訳ポップアップすべてがこのレシピに追従する。 */
  carStressRecipe?: CarStressRecipeOverride;
  /** 車ストレスが参照する「道路適正」の上書き（研究モード、改善計画: 車との近さ
   * 材料の共有元化）。undefinedなら既定レシピ（DEFAULT_ROAD_SUITABILITY_RECIPE）を使う。
   * carStressRecipeと同じ扱いで、地図表示・内訳ポップアップへ同時に反映される。 */
  roadSuitabilityRecipe?: RoadSuitabilityRecipeOverride;
  /** 車ストレスが参照する「自動車密度」の上書き（研究モード）。undefinedなら
   * 既定レシピ（DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE）を使う。roadSuitabilityRecipeと
   * 同じ扱い。 */
  motorVehicleDensityRecipe?: MotorVehicleDensityRecipeOverride;
  /** 指定路線（外部静的データソース T51、KSJ N10/N12）。路面と同じソースを再利用する独立レイヤー。 */
  showDesignation: boolean;
  /** 事故（外部静的データソース T50、警察庁交通事故統計）。road_surfaceとは独立のソース。 */
  showAccidents: boolean;
  /** 停止要因POI（改善計画T54）。路面とは別の点データ用ベクタソースを使う。 */
  showStopPoi: boolean;
  /** 補給・休憩ポイントPOI（改善計画T101、コンビニ・自販機・トイレ・給水・駐輪場）。
   * 停止要因POIと同じベクタソース（region-poi-tiles）を共有する独立レイヤー。 */
  showSupplyPoi: boolean;
  /** 二次軸rampレイヤー（改善計画T145b）の表示フラグ。キーはaxisMapLayerId（"axis:accident"等、
   * mapLayers.tsのMapLayerIdと同じ）。カタログ駆動のため個別のshow*フラグは持たない。 */
  axisVisibility: Record<string, boolean>;
  /** 2次（carStress・ramp軸）のうち、材料（1次）が同時に表示されているためcasing
   * （太く半透明な下敷き）で描くべきレイヤーのkey集合（"carStress"/"axis:accident_density"等、
   * STATIC_OVERLAY_LAYERSのkeyと同じ）。page.tsx側がaxisMaterialLayerIdsとlayerVisibility
   * から算出する（改善計画: 2次の下敷きの副作用対応、applySecondaryAxisCasingStyles参照）。 */
  secondaryAxisCasingLayerIds: readonly string[];
  /** 路面の2軸（路面の種類・道路の種類）それぞれの非表示カテゴリキー。互いに独立な軸なので
   * 常に両方同時に効かせる（色分けは常にROAD_LINE_COLOR_AXIS_IDで固定、選択の余地は無い）。 */
  roadHiddenKeysByMode: Record<RoadFilterAxisId, readonly string[]>;
  /** 車ストレス・自転車インフラ・指定路線・停止要因POI・事故（当事者/重大度）の絞り込み軸
   * （改善計画T63、STATIC_FILTER_AXES参照）。事故のみ2軸を持ち、他は1軸。 */
  staticLegendHiddenKeysByAxis: Record<StaticFilterAxisId, readonly string[]>;
  routeLayerOn: boolean;
  routeStyleModeId: RouteStyleModeId;
  hiddenRouteLegendKeys: readonly string[];
  onRegionZoomHintChange: (tooWide: boolean) => void;
  /** レイヤーごとのデータ取得状態（改善計画T87、loading/empty/error）。表示ONのレイヤーが
   * 変わるたび・タイル取得の進行に応じて呼ばれる（値が変わらない限り呼ばない）。 */
  onLayerDataStatusChange: (status: LayerDataStatusByLayer) => void;
  refreshToken: number;
  /** 実験スロット（研究インターフェース改善 §10-3）。デバッグモードOFF時は呼び出し側が
   * 空配列を渡すため、通常利用ではレイヤーは作られない。 */
  experimentSlots: ExperimentSlot[];
}

export default function MapView({
  routes,
  selectedRouteId,
  location,
  showElevation,
  showPrecipitationNowcast,
  precipitationNowcastTileUrl,
  showWindVector,
  windVectorTileUrl,
  showRoadType,
  showRoadSurface,
  showCarStress,
  showBicycleInfra,
  carStressRecipe,
  roadSuitabilityRecipe,
  motorVehicleDensityRecipe,
  showDesignation,
  showAccidents,
  showStopPoi,
  showSupplyPoi,
  axisVisibility,
  secondaryAxisCasingLayerIds,
  roadHiddenKeysByMode,
  staticLegendHiddenKeysByAxis,
  routeLayerOn,
  routeStyleModeId,
  hiddenRouteLegendKeys,
  onRegionZoomHintChange,
  onLayerDataStatusChange,
  refreshToken,
  experimentSlots,
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
  // 初期表示直後は基礎地図タイルの取得が終わるまで数秒間ほぼ白紙のまま何も見えず、
  // 初めて開いたユーザーには「壊れている」ように映りかねなかった。最初のidle
  // （表示中のタイル取得が一通り落ち着いたタイミング）までスケルトンを重ねて示す。
  const [initialTilesLoading, setInitialTilesLoading] = useState(true);
  const onRegionZoomHintChangeRef = useRef(onRegionZoomHintChange);
  const onLayerDataStatusChangeRef = useRef(onLayerDataStatusChange);
  const redrawPropsRef = useRef({
    routes,
    selectedRouteId,
    routeLayerOn,
    routeStyleModeId,
    hiddenRouteLegendKeys,
    showElevation,
    showPrecipitationNowcast,
    precipitationNowcastTileUrl,
    showWindVector,
    windVectorTileUrl,
    showRoadType,
    showRoadSurface,
    showCarStress,
    showBicycleInfra,
    carStressRecipe,
    roadSuitabilityRecipe,
    motorVehicleDensityRecipe,
    showDesignation,
    showAccidents,
    showStopPoi,
    showSupplyPoi,
    axisVisibility,
    secondaryAxisCasingLayerIds,
    roadHiddenKeysByMode,
    staticLegendHiddenKeysByAxis,
    experimentSlots,
  });

  const selectedCandidate = routes.find((r) => r.id === selectedRouteId) ?? null;

  useEffect(() => {
    onRegionZoomHintChangeRef.current = onRegionZoomHintChange;
  }, [onRegionZoomHintChange]);

  useEffect(() => {
    onLayerDataStatusChangeRef.current = onLayerDataStatusChange;
  }, [onLayerDataStatusChange]);

  useEffect(() => {
    redrawPropsRef.current = {
      routes,
      selectedRouteId,
      routeLayerOn,
      routeStyleModeId,
      hiddenRouteLegendKeys,
      showElevation,
      showPrecipitationNowcast,
      precipitationNowcastTileUrl,
      showWindVector,
      windVectorTileUrl,
      showRoadType,
      showRoadSurface,
      showCarStress,
      showBicycleInfra,
      carStressRecipe,
      roadSuitabilityRecipe,
      motorVehicleDensityRecipe,
      showDesignation,
      showAccidents,
      showStopPoi,
      showSupplyPoi,
      axisVisibility,
      secondaryAxisCasingLayerIds,
      roadHiddenKeysByMode,
      staticLegendHiddenKeysByAxis,
      experimentSlots,
    };
  }, [
    routes,
    selectedRouteId,
    routeLayerOn,
    routeStyleModeId,
    hiddenRouteLegendKeys,
    showElevation,
    showPrecipitationNowcast,
    precipitationNowcastTileUrl,
    showWindVector,
    windVectorTileUrl,
    showRoadType,
    showRoadSurface,
    showCarStress,
    showBicycleInfra,
    carStressRecipe,
    roadSuitabilityRecipe,
    motorVehicleDensityRecipe,
    showDesignation,
    showAccidents,
    showStopPoi,
    showSupplyPoi,
    axisVisibility,
    secondaryAxisCasingLayerIds,
    roadHiddenKeysByMode,
    staticLegendHiddenKeysByAxis,
    experimentSlots,
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
      showPrecipitationNowcast,
      precipitationNowcastTileUrl,
      showWindVector,
      windVectorTileUrl,
      showRoadType,
      showRoadSurface,
      showCarStress,
      showBicycleInfra,
      carStressRecipe,
      roadSuitabilityRecipe,
      motorVehicleDensityRecipe,
      showDesignation,
      showAccidents,
      showStopPoi,
      showSupplyPoi,
      axisVisibility,
      secondaryAxisCasingLayerIds,
      roadHiddenKeysByMode,
      staticLegendHiddenKeysByAxis,
      experimentSlots,
    } = redrawPropsRef.current;
    setStaticOverlayVisibility(map, {
      elevation: showElevation,
      carStress: showCarStress,
      bicycleInfra: showBicycleInfra,
      designation: showDesignation,
      accidents: showAccidents,
      stopPoi: showStopPoi,
      supplyPoi: showSupplyPoi,
      ...axisVisibility,
    });
    applySecondaryAxisCasingStyles(map, new Set(secondaryAxisCasingLayerIds));
    applyPrecipitationNowcastState(map, showPrecipitationNowcast, precipitationNowcastTileUrl);
    applyWindVectorState(map, showWindVector, windVectorTileUrl);
    setStaticOverlayFilters(
      map,
      staticLegendHiddenKeysByAxis,
      carStressRecipe ?? DEFAULT_CAR_STRESS_RECIPE,
      roadSuitabilityRecipe ?? DEFAULT_ROAD_SUITABILITY_RECIPE,
      motorVehicleDensityRecipe ?? DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    );
    applyRoadLayerState(map, showRoadSurface, showRoadType, roadHiddenKeysByMode);
    applyRoadMaterialTrackOffsets(map, {
      road: showRoadSurface || showRoadType,
      bicycleInfra: showBicycleInfra,
      designation: showDesignation,
    });
    updateRoadZoomHint(
      map,
      isRoadSurfaceGroupVisible({
        roadType: showRoadType,
        roadSurface: showRoadSurface,
        carStress: showCarStress,
        bicycleInfra: showBicycleInfra,
        designation: showDesignation,
      }),
      onRegionZoomHintChangeRef.current
    );

    drawBaseRoutes(map, routes, selectedRouteId);
    if (routes.length > 0) fitBoundsToRoutes(map, routes);
    drawSelectedOutline(map, routes, selectedRouteId);
    drawExperimentSlots(map, experimentSlots);

    const selected = routes.find((r) => r.id === selectedRouteId) ?? null;
    if (routeLayerOn && selected?.segments) {
      drawDetailSegments(map, selected.segments, getRouteStyleMode(routeStyleModeId), hiddenRouteLegendKeys);
    } else {
      hideDetailSegments(map);
    }
  }, []);

  // T87: レイヤーデータ状態（loading/empty/error）の状態管理・再計算はuseLayerDataStatus
  // （改善計画T123）に集約されている。ここでは「今の表示ON/OFFフラグをどう読むか」だけを
  // 安定した関数として渡す（redrawPropsRef自体を渡さないのは、フック側をrefの内部構造に
  // 依存させないため）。
  const getLayerVisibility = useCallback(() => {
    const {
      showElevation,
      showRoadType,
      showRoadSurface,
      showCarStress,
      showBicycleInfra,
      showDesignation,
      showAccidents,
      showStopPoi,
      showSupplyPoi,
      axisVisibility,
    } = redrawPropsRef.current;
    return {
      elevation: showElevation,
      roadType: showRoadType,
      roadSurface: showRoadSurface,
      carStress: showCarStress,
      bicycleInfra: showBicycleInfra,
      designation: showDesignation,
      accidents: showAccidents,
      stopPoi: showStopPoi,
      supplyPoi: showSupplyPoi,
      ...axisVisibility,
    };
  }, []);
  // useLayerDataStatusは呼び出しのたびに新しいオブジェクトを返すため、依存配列に安定した
  // 参照を渡せるよう個々の関数を分割代入する（layerDataStatus.recomputeのようにプロパティ
  // アクセスのまま依存配列へ書くと、react-hooks/exhaustive-depsがオブジェクト全体への依存を
  // 要求してしまう）。
  const { recompute: recomputeLayerDataStatus, markSourceErrored, clearSourceLoading, notifySourceData, settleViewport } =
    useLayerDataStatus({
      mapRef,
      layerDataSources: LAYER_DATA_SOURCES,
      getVisibility: getLayerVisibility,
      onChangeRef: onLayerDataStatusChangeRef,
    });

  // 地図初期化
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    // アンマウント後にidleイベントが届いてもsetStateしないためのガード
    // （BackendStatusのcancelledガードと同じ考え方）
    let cancelled = false;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE,
      center: [location.longitude, location.latitude],
      zoom: 13,
      attributionControl: { compact: true },
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

    // MapLibreのAttributionControlは既定でcompact:true（ⓘアイコン化）だが、初期化直後は
    // まだ属性表示するデータが無く"maplibregl-attrib-empty"のため、この時点ではコンパクト
    // 化のクラスがまだ付いていない。スタイル読み込み完了後にstyledata/sourcedataイベント
    // 経由でMapLibre内部が初めて属性データを反映するタイミングで"maplibregl-compact"と
    // 同時に"maplibregl-compact-show"（展開状態＝「MapLibre | © OpenFreeMap」の全文表示）も
    // 付与される。ユーザーが一度でも地図をドラッグすればdragイベントで自動的に閉じるが、
    // それまでの間は他のUI（レイヤーチップ等）と重なって読みにくい、という実機フィードバックの
    // 原因になっていた。AttributionControl自身と同じイベント（styledata/sourcedata）を
    // 購読し、都度コンパクト表示（アイコンのみ）へ揃える（「変わらないデータを更新」による
    // setStyle再読み込み時の再発にも同じ仕組みで対応できる）。
    const attribEl = mapContainerRef.current?.querySelector(".maplibregl-ctrl-attrib");
    function collapseAttribution() {
      attribEl?.classList.remove("maplibregl-compact-show");
    }
    map.on("styledata", collapseAttribution);
    map.on("sourcedata", collapseAttribution);

    // MapLibre自体もコンテナの内蔵ResizeObserverでの自動追従を持つが、デバッグモード時に
    // 実機で「地図が画面幅の一部にしか描画されず残りが黒くなる」不具合を確認した
    // （キャンバスのCSS幅がコンテナ幅より狭い値に固定されたまま更新されない）。原因は
    // デバッグログの流入（タイル要求ごとにdebugLog→DebugConsole再レンダー→自動スクロール、
    // モバイル実機フィードバック対応T34のisMobile確定に伴うレイアウト変化と重なる）が
    // 内蔵ResizeObserverの通知を取りこぼすことと推測されるが、根本原因の特定に関わらず
    // 「コンテナの実サイズ変化を検知したら明示的にmap.resize()する」独自の
    // ResizeObserverを持たせるのが素直な対策のため、内蔵の自動追従に上乗せする形で追加する。
    const resizeObserver = new ResizeObserver(() => {
      mapRef.current?.resize();
    });
    resizeObserver.observe(mapContainerRef.current);
    // 標高ラスタ・路面ベクタタイルは他の重ね描きレイヤーより先に追加し、常に背景寄りに
    // 描画されるようにする（標高が最背面、その上に路面、さらに上にルート系レイヤー）。
    // ensureAllStaticOverlayLayers内のcarStress/bicycleInfra/designationはROAD_TILE_SOURCE_ID
    // （road_surfaceベクタソース）を再利用する依存関係があるため、そのソースを実際に作る
    // ensureRoadSurfaceTileLayerを先に呼ぶ必要がある。いずれも初回はmap.once("load", ...)への
    // 登録（実行はスタイル読み込み完了後）のため、ここでの呼び出し順がそのまま発火順になる。
    // 以前はensureAllStaticOverlayLayers（elevationも含む）がensureRoadSurfaceTileLayerより
    // 先だったため、carStress等のaddLayerがソース未作成のまま実行され
    // 「source "region-road-surface-tiles" not found」エラーが発生していた（実機フィードバックで
    // 発覚）。標高を先に単独ensureしてから路面ソースを作ることで「標高が最背面、その上に路面」
    // の意図を保ったまま直す（ensureAllStaticOverlayLayers内でelevationが二重に呼ばれるが
    // 自身のガードで無害化される）。
    STATIC_OVERLAY_LAYERS.find((layer) => layer.key === "elevation")?.ensure(map);
    ensureRoadSurfaceTileLayer(map);
    ensureAllStaticOverlayLayers(map);

    // 路面レイヤーの区間・ルートレイヤーの詳細区間をクリックすると詳細をポップアップ表示する
    // （標高はラスタタイルのため、地物ごとのクリック判定は行わない）
    function handleClick(e: MapMouseEvent) {
      const layers = INTERACTIVE_LAYER_IDS.filter((id) => map.getLayer(id));
      if (layers.length === 0) return;
      const features = map.queryRenderedFeatures(e.point, { layers });
      if (features.length === 0) return;

      const feature = features[0];
      const isRoadSurfaceFeature =
        feature.layer.id !== DETAIL_LAYER_ID &&
        feature.layer.id !== ACCIDENT_LAYER_ID &&
        feature.layer.id !== STOP_POI_LAYER_ID &&
        feature.layer.id !== SUPPLY_POI_LAYER_ID;
      // car_stressはタイルに計算済みの値として焼き込まれていない（改善計画: 車ストレス
      // レシピ外出し基盤）ため、クリックされたフィーチャーの材料タグからここで計算する
      // （地図の色分け・凡例フィルタと同じexpressionをcarStressExpression.tsで共有する）。
      // このhandleClickは地図初期化時（マウント時1回）のuseEffectで定義され以降作り直されない
      // ため、propsを直接閉じ込めずredrawPropsRef.current経由で最新のレシピ上書き値を読む
      // （redrawAllLayersと同じ理由、上のコメント群参照）。
      const currentCarStressRecipe = redrawPropsRef.current.carStressRecipe ?? DEFAULT_CAR_STRESS_RECIPE;
      // 車ストレスが参照する「車との近さ」(N2)の材料（改善計画: 車との近さ材料の
      // 共有元化）。上のcurrentCarStressRecipeと同じ理由でredrawPropsRef.current経由。
      const currentRoadSuitabilityRecipe =
        redrawPropsRef.current.roadSuitabilityRecipe ?? DEFAULT_ROAD_SUITABILITY_RECIPE;
      const currentMotorVehicleDensityRecipe =
        redrawPropsRef.current.motorVehicleDensityRecipe ?? DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE;
      const roadSurfaceProperties = {
        ...(feature.properties as unknown as RoadSurfacePopupProperties),
        car_stress: isRoadSurfaceFeature
          ? evaluateCarStressLevel(
              feature.properties ?? {},
              currentCarStressRecipe,
              currentRoadSuitabilityRecipe,
              currentMotorVehicleDensityRecipe,
            )
          : null,
      };
      const html =
        feature.layer.id === DETAIL_LAYER_ID
          ? buildSegmentPopupHtml(feature.properties as unknown as RouteSegmentProperties)
          : feature.layer.id === ACCIDENT_LAYER_ID
            ? buildAccidentPopupHtml(feature.properties as unknown as AccidentPopupProperties)
            : feature.layer.id === STOP_POI_LAYER_ID
              ? buildStopPoiPopupHtml(feature.properties as unknown as StopPoiPopupProperties)
              : feature.layer.id === SUPPLY_POI_LAYER_ID
                ? buildSupplyPoiPopupHtml(feature.properties as unknown as SupplyPoiPopupProperties)
                : buildRoadSurfacePopupHtml(roadSurfaceProperties);

      popupRef.current?.remove();
      popupRef.current = new maplibregl.Popup({ closeButton: true }).setLngLat(e.lngLat).setHTML(html).addTo(map);

      // 車ストレスの内訳ボタン（改善計画T90）は道路レイヤーかつcar_stressが
      // 判定済みの区間だけに出るため、buildRoadSurfacePopupHtml側の出し分けと対応させる。
      if (isRoadSurfaceFeature && roadSurfaceProperties.car_stress != null && roadSurfaceProperties.osm_way_id != null) {
        const popupElement = popupRef.current.getElement();
        if (popupElement) {
          attachCarStressBreakdownHandler(
            popupElement,
            roadSurfaceProperties.osm_way_id,
            currentCarStressRecipe,
            currentRoadSuitabilityRecipe,
            currentMotorVehicleDensityRecipe,
          );
        }
      }
      // 区間インスペクタ（改善計画T146）はbuildRoadSurfacePopupHtml側でosm_way_idの
      // 有無だけを見て出しているため、配線側も同じ条件（isRoadSurfaceFeature不要、
      // 道路以外のフィーチャーにはosm_way_id自体が無い）に揃える。
      if (roadSurfaceProperties.osm_way_id != null) {
        const popupElement = popupRef.current.getElement();
        if (popupElement) {
          attachAxisInspectorHandler(
            popupElement,
            roadSurfaceProperties.osm_way_id,
            currentCarStressRecipe,
            currentRoadSuitabilityRecipe,
            currentMotorVehicleDensityRecipe,
          );
        }
      }
    }

    function handleMouseMove(e: MapMouseEvent) {
      const layers = INTERACTIVE_LAYER_IDS.filter((id) => map.getLayer(id));
      if (layers.length === 0) {
        map.getCanvas().style.cursor = "";
        return;
      }
      const features = map.queryRenderedFeatures(e.point, { layers });
      map.getCanvas().style.cursor = features.length > 0 ? "pointer" : "";
    }

    // 路面はベクタタイルのminzoom未満だと描画されないため、ズームのたびに現在のズームと
    // 閾値を比較して「表示範囲が広すぎます」の案内を更新する（データ取得は発生しない、
    // 単なる数値比較なので毎フレーム呼ばれても軽い）。専用のrefを持たず、常に最新の
    // propsを保持するredrawPropsRef.currentを直接読む（getLayerVisibilityと同じ方式）。
    function handleZoom() {
      const { showRoadType, showRoadSurface, showCarStress, showBicycleInfra, showDesignation } =
        redrawPropsRef.current;
      updateRoadZoomHint(
        map,
        isRoadSurfaceGroupVisible({
          roadType: showRoadType,
          roadSurface: showRoadSurface,
          carStress: showCarStress,
          bicycleInfra: showBicycleInfra,
          designation: showDesignation,
        }),
        onRegionZoomHintChangeRef.current
      );
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
      debugLog("map:error", e.error?.message ?? "unknown error", { sourceId }, "error");
      // スタイル自体がまだ一度もreadyになっていない状態でのerrorは、個別タイルの一過性の
      // 失敗ではなくスタイル取得そのものの失敗である可能性が高い（runWhenStyleReadyが
      // 頼るmap.once("load", ...)がこの後発火しないままdrawBaseRoutes等の描画コールバックが
      // 永久にスキップされる）。デバッグモードに関わらずユーザーへ気づけるようにする。
      const tagged = map as unknown as { __rcStyleReady?: boolean };
      if (!tagged.__rcStyleReady) {
        setStyleLoadFailed(true);
        setInitialTilesLoading(false);
      }
      // T87: レイヤーデータ状態の対象sourceで起きたエラーは「取得失敗」として記録する
      // （エラー解除はhandleTrackedSourceDataLoading側、新しい取得サイクルの開始時のみ）。
      if (sourceId) markSourceErrored(sourceId);
    }
    function handleFirstIdle() {
      if (cancelled) return;
      setInitialTilesLoading(false);
      recomputeLayerDataStatus();
    }
    // T87: レイヤーデータ状態の対象sourceのタイル取得イベント。新しい取得サイクルの
    // 開始（sourcedataloading）で直前のエラー状態をクリアし、進行・完了（sourcedata）の
    // たびに再計算する（loading/empty/errorいずれも、実際の変化がなければ
    // recompute内でコールバックを呼ばない）。
    function handleTrackedSourceDataLoading(e: maplibregl.MapSourceDataEvent) {
      clearSourceLoading(e.sourceId);
    }
    function handleTrackedSourceData(e: maplibregl.MapSourceDataEvent) {
      notifySourceData(e.sourceId);
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
    }
    function handleZoomEnd() {
      debugLog("map:viewport", "zoomend", { zoom: Number(map.getZoom().toFixed(2)) });
      settleViewport();
    }
    // T87実機確認で判明した不具合の対策その2: isSourceLoaded()がtrueになった直後の一瞬は
    // querySourceFeatures()がまだ実際のフィーチャーを返さないタイミングがあり
    // （isSourceLoadedとタイルのパース完了の間に競合がある）、その瞬間にsourcedataイベントで
    // 再計算すると誤って"empty"と判定・確定してしまう。その後実際にフィーチャーが揃っても、
    // 状態を変える追加のsourcedataイベントが来ないため、誤ったempty表示のまま固定されてしまう
    // 不具合を実機で確認した（road_surfaceに実際は6,273件あるのに「データなし」のまま）。
    // "idle"（描画が一通り落ち着いた状態、sourcedataより後発で頻度は低い）でも継続的に
    // 再計算することで、この種のズレを取りこぼさず収束させる。
    // 注意: ここではsettleViewport（clearStaleTrackedSourceErrors）を呼ばない
    // （handleMoveEnd/handleZoomEndとの
    // 非対称は意図的）。"idle"はビューポートが変わっていなくても発火する（ポップアップを開く・
    // マーカー移動等）ため、"isSourceLoaded()がtrue"であっても「今まさに進行中の障害で
    // 該当タイルがerrored状態のまま留まっている」場合と区別できない
    // （MapLibreのTileManager.loaded()は'errored'状態のタイルも'loaded'と同様に「保留中の
    // 要求が無い」と扱うため、リトライされないまま即座にtrueを返しうる）。moveend/zoomendは
    // 定義上ビューポートが実際に変わった時にしか発火しないため、そちらでのisSourceLoaded()の
    // trueは「新しいビューポートには（把握できる範囲で）問題が無い」という意味を持てるが、
    // "idle"でのtrueにはその保証が無く、進行中の実障害を「解除」してしまう
    // （バックエンド障害中に"idle"で誤ってerrorが消え、"データなし"に化けるレビュー指摘で発覚）。
    function handleIdleRecompute() {
      recomputeLayerDataStatus();
    }

    map.on("click", handleClick);
    map.on("mousemove", handleMouseMove);
    map.on("zoom", handleZoom);
    map.on("load", handleLoad);
    map.on("error", handleMapError);
    map.on("moveend", handleMoveEnd);
    map.on("zoomend", handleZoomEnd);
    map.on("sourcedataloading", handleTrackedSourceDataLoading);
    map.on("sourcedata", handleTrackedSourceData);
    map.on("idle", handleIdleRecompute);
    map.once("idle", handleFirstIdle);

    return () => {
      cancelled = true;
      resizeObserver.disconnect();
      map.off("styledata", collapseAttribution);
      map.off("sourcedata", collapseAttribution);
      map.off("click", handleClick);
      map.off("mousemove", handleMouseMove);
      map.off("zoom", handleZoom);
      map.off("load", handleLoad);
      map.off("error", handleMapError);
      map.off("moveend", handleMoveEnd);
      map.off("zoomend", handleZoomEnd);
      map.off("sourcedataloading", handleTrackedSourceDataLoading);
      map.off("sourcedata", handleTrackedSourceData);
      map.off("idle", handleIdleRecompute);
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

  // 実験スロットの重ね描き（研究インターフェース改善 §10-3）。デバッグモードOFF時は
  // 呼び出し側（page.tsx）が空配列を渡すため、レイヤーは作られるが常に空になる。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    drawExperimentSlots(map, experimentSlots);
  }, [experimentSlots]);

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

  // 標高・車ストレス・自転車インフラ・指定路線・事故・停止要因POI・補給休憩POI
  // （T101）は、いずれも「選択候補に関係なく地図全体に重ね描きし、切替はvisibilityの差し替え
  // のみ」という同型のレイヤー（STATIC_OVERLAY_LAYERS）のため、1つのeffectでまとめて反映する
  // （改善計画T47 R-6の宣言的ループ化。setLayerVisibilityは同じ値の再設定でも副作用が無いため、
  // いずれか1つのフラグが変わったときに他を再設定しても表示に影響しない）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    setStaticOverlayVisibility(map, {
      elevation: showElevation,
      carStress: showCarStress,
      bicycleInfra: showBicycleInfra,
      designation: showDesignation,
      accidents: showAccidents,
      stopPoi: showStopPoi,
      supplyPoi: showSupplyPoi,
      ...axisVisibility,
    });
    applySecondaryAxisCasingStyles(map, new Set(secondaryAxisCasingLayerIds));
    // T87: OFF→ONで新たに可視になったレイヤー、またはOFFになったレイヤーの状態表示を
    // 即座に反映する（タイルが既にキャッシュ済みでsourcedataイベントが発火しない場合でも
    // 状態が更新されるようにするため）。
    recomputeLayerDataStatus();
  }, [
    showElevation,
    showCarStress,
    showBicycleInfra,
    showDesignation,
    showAccidents,
    showStopPoi,
    showSupplyPoi,
    axisVisibility,
    secondaryAxisCasingLayerIds,
    recomputeLayerDataStatus,
  ]);

  // 降水ナウキャスト・風の矢印（改善計画T170/T171/T178）。どちらもtileUrl/sourceUrlが
  // 地図上の時刻スライダー操作のたびに変わるため、上のSTATIC_OVERLAY_LAYERS一括effect
  // （依存が多く再実行コストの大きいshowX系フラグ群）とは分けた専用effectにまとめる
  // （2レイヤーとも同じ「時刻依存レイヤー」の性質のため1本のeffectで足りる）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyPrecipitationNowcastState(map, showPrecipitationNowcast, precipitationNowcastTileUrl);
    applyWindVectorState(map, showWindVector, windVectorTileUrl);
    recomputeLayerDataStatus();
  }, [showPrecipitationNowcast, precipitationNowcastTileUrl, showWindVector, windVectorTileUrl, recomputeLayerDataStatus]);

  // 車ストレス・自転車インフラ・指定路線・停止要因POI・補給休憩POI（T101）・
  // 事故（当事者/重大度）の絞り込み（改善計画T63）。
  // 道路情報のフィルタ効果（下）と同じくvisibility/フィルタ式の差し替えのみで反映される。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    setStaticOverlayFilters(
      map,
      staticLegendHiddenKeysByAxis,
      carStressRecipe ?? DEFAULT_CAR_STRESS_RECIPE,
      roadSuitabilityRecipe ?? DEFAULT_ROAD_SUITABILITY_RECIPE,
      motorVehicleDensityRecipe ?? DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    );
  }, [
    staticLegendHiddenKeysByAxis,
    carStressRecipe,
    roadSuitabilityRecipe,
    motorVehicleDensityRecipe,
  ]);

  // 路面（道路の種類/路面の種類、改善計画T165）ON/OFF・凡例フィルタの切替は、いずれも
  // visibility/paint/フィルタ式の差し替えのみで反映される（データ取得はMapLibreがパン/
  // ズームに応じて自動で行うため、明示的なfetchは不要）。色・太さ・線種は
  // showRoadSurface/showRoadTypeの組み合わせでapplyRoadLayerStateが都度再計算する
  // （固定ではなくなった、applyRoadLayerStateのコメント参照）。
  // regionZoomTooWide（ズーム範囲外の案内）はroad_surfaceタイルを共有するcarStress/
  // bicycleInfra/designationのON/OFFでも変わりうるため、依存配列に含めてこれらの
  // フラグが変わるたびにも再評価する（改善計画T87レビュー指摘: road自体はOFFのままcarStress等
  // だけONで表示範囲が広すぎる場合に案内が一切出なかった不整合の修正）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyRoadLayerState(map, showRoadSurface, showRoadType, roadHiddenKeysByMode);
    applyRoadMaterialTrackOffsets(map, {
      road: showRoadSurface || showRoadType,
      bicycleInfra: showBicycleInfra,
      designation: showDesignation,
    });
    updateRoadZoomHint(
      map,
      isRoadSurfaceGroupVisible({
        roadType: showRoadType,
        roadSurface: showRoadSurface,
        carStress: showCarStress,
        bicycleInfra: showBicycleInfra,
        designation: showDesignation,
      }),
      onRegionZoomHintChangeRef.current
    );
    recomputeLayerDataStatus();
  }, [
    showRoadType,
    showRoadSurface,
    showCarStress,
    showBicycleInfra,
    showDesignation,
    roadHiddenKeysByMode,
    recomputeLayerDataStatus,
  ]);

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
        debugLog(
          "map:error",
          `basemap refresh failed: ${error instanceof Error ? error.message : String(error)}`,
          undefined,
          "error",
        );
      }
    })();
  }, [refreshToken, redrawAllLayers]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />
      {initialTilesLoading && !styleLoadFailed && (
        <div className={styles.loadingOverlay} aria-hidden="true">
          <span className={styles.spinner} />
          <span className={styles.loadingText}>地図を読み込み中…</span>
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
            background: "#fef2f2",
            color: "#991b1b",
            border: "1px solid #fecaca",
            borderRadius: "0.5rem",
            padding: "0.5rem 1rem",
            fontSize: "0.85rem",
            boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
            zIndex: 10,
            // 押せないメッセージ表示のため地図へタッチを素通しする（MapOverlayControlsの
            // 隙間と同じ理由。既定のpointer-events: autoのままだとピンチの片方の指が
            // ここに乗ったときページ全体のネイティブズームに化る）。
            pointerEvents: "none",
          }}
        >
          地図の読み込みに失敗しました。しばらくしてから再読み込みしてください。
        </div>
      )}
    </div>
  );
}

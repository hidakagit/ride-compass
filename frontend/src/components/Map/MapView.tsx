"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { labelOrEscapedRaw } from "@/components/Map/popupEscape";
import RoadInspectorPopup from "@/components/Map/RoadInspectorPopup";
import type { RoadSurfacePopupProperties } from "@/components/Map/roadFacts";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import * as maplibregl from "maplibre-gl";
import type {
  ErrorEvent as MapLibreErrorEvent,
  GeoJSONSource,
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
  RouteSegmentDetail,
  SelectedRouteSegment,
} from "@/types/route";
import type { ExperimentSlot } from "@/types/experimentSlot";
import {
  LANDCOVER_TILE_MAX_ZOOM,
  LANDCOVER_TILE_MIN_ZOOM,
  ROAD_TILE_MAX_ZOOM,
  ROAD_TILE_MIN_ZOOM,
  accidentTileUrl,
  landcoverTileUrl,
  poiTileUrl,
  roadSurfaceTileUrl,
} from "@/services/regionApi";
import {
  KNOWN_LINE_OPACITY,
  ROAD_SURFACE_AXIS_ID,
  ROAD_TYPE_AXIS_ID,
  getRoadFilterAxis,
  type RoadFilterAxisId,
} from "@/components/Map/roadFilterAxes";
import { getRouteStyleMode, type RouteStyleMode, type RouteStyleModeId } from "@/components/Map/routeStyleModes";
import {
  ORIGIN_MARK_COLOR,
  ORIGIN_MARK_FALLBACK_COLOR,
  PIN_MARK_BACKGROUND,
  pinMarkHtml,
} from "@/components/Map/pinMarks";
import { buildCombinedLegendFilterExpression } from "@/components/Map/legendFilter";
import {
  ACCIDENT_COLOR_EXPRESSION,
  ACCIDENT_RADIUS_EXPRESSION,
  DESIGNATION_COLOR_EXPRESSION,
  DESIGNATION_OPACITY_EXPRESSION,
  TUNNEL_COLOR_EXPRESSION,
  TUNNEL_OPACITY_EXPRESSION,
  ONEWAY_COLOR_EXPRESSION,
  ONEWAY_OPACITY_EXPRESSION,
  STOP_POI_COLOR_EXPRESSION,
  STOP_POI_LABELS,
  SUPPLY_POI_COLOR_EXPRESSION,
  SUPPLY_POI_LABELS,
  buildStaticFilterAxes,
  type StaticFilterAxis,
  type StaticFilterAxisId,
} from "@/components/Map/staticAttributeLayers";
import {
  buildRoadSurfaceSharedLayerIds,
  type LayerDataStatusByLayer,
  type MapLayerId,
} from "@/components/Map/mapLayers";
import { WIND_CALM_THRESHOLD_MS, WIND_SPEED_COLOR_STOPS } from "@/components/Map/windLayer";
import {
  dedicatedWayValueColorExpression,
  dedicatedWayValueFeatureStateKey,
  type DedicatedWayValueDisplay,
} from "@/components/Map/dedicatedWayValueLayer";
import { PRECIPITATION_COLOR_STOPS, PRECIPITATION_NONE_THRESHOLD_MM } from "@/components/Map/precipitationNowcast";
import { tileBaseUrl } from "@/lib/tileBaseUrl";
import { createLidenIcon } from "@/components/Map/lidenIcon";
import { LIDEN_MARK_VALUE_PROPERTY } from "@/components/Map/lidenLayer";
import { RISK_LEVEL_COLORS } from "@/components/Map/riskMap";
import { createWindArrowIcon } from "@/components/Map/windArrowIcon";
import { runWhenStyleReady, setLayerVisibility, zoomAndPropertyIconSizeExpression } from "@/components/Map/mapStyleOps";
import {
  applyRouteLayerVisibility,
  DETAIL_HIT_LAYER_ID,
  drawDetailSegments,
  drawExperimentSlots,
  drawSpliceStretches,
  drawSplicedRoute,
  hideDetailSegments,
  hideSpliceStretches,
  hideSplicedRoute,
  restoreRouteSegmentProperties,
  ROUTES_HIT_LAYER_ID,
  SPLICE_HIT_LAYER_ID,
  type RouteSegmentProperties,
  type SpliceStretchFeature,
} from "@/components/Map/MapView.routes";
import {
  DYNAMIC_WEATHER_LAYER_IDS,
  type DynamicWeatherGroupState,
  type DynamicWeatherLayerId,
  type DynamicWeatherSourceId,
} from "@/components/Map/dynamicWeather";
import {
  axisLineLayerId,
  axisMapLayerId,
  buildAxisRampColorExpression,
  dedicatedWayValueLineLayerId,
  dedicatedWayValueMapLayerId,
  type DedicatedWayValueAxis,
  type RampAxis,
} from "@/components/Map/axisLayers";
import { useLayerDataStatus } from "@/components/Map/useLayerDataStatus";
import { useJmaTileIndex } from "@/hooks/useJmaTileIndex";
import { jmaPlaceholderTileUrl } from "@/components/Map/jmaNowcastFrames";
import { registerJmaTileProtocol, withJmaTileProtocol } from "@/components/Map/jmaTileProtocol";
import jmaTileConfig from "@/types/generated/jma-tile-config.json";
import { debugLog } from "@/lib/debugLog";
import styles from "./MapView.module.css";

// 基礎地図のスタイルJSON。オリジンは`tileBaseUrl()`（lib/tileBaseUrl.ts: 既定はフロント
// 自身のオリジン＝Next.jsのrewrites経由、`NEXT_PUBLIC_TILE_BASE_URL`設定時はbackend直接）
// に従う。スタイルJSON内のタイル・スプライト・グリフのURLはbackendが
// `basemap_public_base_url`（BASEMAP_PUBLIC_BASE_URL）で組み立てるため、両者は同じ
// オリジンを指すよう揃える必要がある。
const MAP_STYLE_PATH = "/api/basemap/styles/liberty";
function mapStyleUrl(): string {
  return `${tileBaseUrl()}${MAP_STYLE_PATH}`;
}

// 出発地点マーカーは、「現在地に移動」ボタン（page.tsx）と同じSVG（十字線+中心ドット、
// 地図アプリの現在地アイコンの定番形状）を白背景の円に乗せて共通化する。maplibregl.Marker
// 既定のしずく形（下端が地点を指す）と違いこの形は左右対称なため、アンカーを"bottom"では
// なく"center"にする（地点＝アイコンの中心）。
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

// 経由地・目的地のピン。3つの地点はどれも「つかんで動かせる」ため、見た目も同じ丸い
// バッジで揃える（出発地=createOriginMarkerElement、色と中身だけが違う）。白縁と影は
// 地図のどの配色の上でも輪郭が消えないために要る。
// touch-action:noneが無いと、地図をドラッグでパンしようとした指の起点がこの要素に乗った
// 場合、ブラウザが要素自身のタッチ挙動（既定=auto）を優先してMapLibre側のパンジェスチャー
// として確定しないことがある（.locateButtonが同じ理由で持っている対策と同じもの）。
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

// 国土地理院の色別標高図（ラスタタイル、APIキー不要）。basemap/jma-tileと同じ
// バックエンド経由（永続ファイルキャッシュ付き）・同一オリジンで配信する。
const GSI_RELIEF_TILE_PATH = "/api/gsi-relief-tile/xyz/relief/{z}/{x}/{y}.png";
const GSI_RELIEF_MAX_ZOOM = 15;
const GSI_RELIEF_ATTRIBUTION =
  '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noreferrer">地理院タイル(色別標高図)</a>';

// 路面ベクタタイル（ROAD_TILE_SOURCE_ID）へ焼き込まれる生データの帰属表示。1つのMVTタイルへ
// OSM（道路本体）・国土数値情報N10/N12（指定路線）・警察庁（事故密度）・Esri×Impact
// Observatory×Microsoft（土地被覆、開放度軸[T624]）の4系統が混在するため、ソースは1つでも
// 帰属表示は4者ぶんまとめて1文字列にする。
const ROAD_TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a> / ' +
  "国土数値情報（国土交通省） / 警察庁 / " +
  '土地被覆: <a href="https://livingatlas.arcgis.com/landcover/" target="_blank" rel="noreferrer">Esri, Impact Observatory, Microsoft</a> (CC BY 4.0)';

// 路面のベクタタイル内のレイヤー名。バックエンド（infrastructure/vector_tile.pyの
// ROAD_SURFACE_LAYER_NAME）と一致させる必要がある（export_openapi.pyが書き出す
// generated/region-tile-config.jsonとregionTileConfig.test.tsの照合テストがドリフトを
// 検知する。exportしているのはそのテストから参照するため）。
export const ROAD_TILE_SOURCE_LAYER = "road_surface";

// 事故レイヤー（外部静的データソース）のベクタタイル内のレイヤー名。バックエンド
// （infrastructure/vector_tile.pyのACCIDENT_LAYER_NAME）と一致させる（ROAD_TILE_SOURCE_LAYERと
// 同じドリフト検知の仕組み、region-tile-config.jsonのaccidentキー）。
export const ACCIDENT_TILE_SOURCE_LAYER = "accidents";

// 停止要因POIタイル内のレイヤー名。バックエンド
// （infrastructure/vector_tile.pyのSTOP_POI_LAYER_NAME）と一致させる必要がある
// （ROAD_TILE_SOURCE_LAYERと同じくregion-tile-config.json経由でドリフト検知、
// regionApi.test.ts参照）。同じpoi-tilesタイルにバックエンドは交差点密度（intersection）も
// 焼き込んでいるが、地図上の独立可視化レイヤーとしては提供しない（道が何本交わっているかは
// 道路網を見れば分かり、可視化としての追加情報が薄いため。材料
// `intersection_count_per_km`としては軸スタジオから引き続き選べる）ためフロント側では参照しない。
export const STOP_POI_SOURCE_LAYER = "stop_poi";

// 初期表示の覆い（「地図を読み込み中…」）を出しておく上限。覆いは最初の数秒の白紙を
// 隠すためのもので、それを過ぎても残ると、描けている地図を隠して壊れているように見せる。
// MapLibreの"idle"は表示中のすべての取得が落ち着くまで来ないため、外部データ
// （既定ONの災害タイル等）が遅いセッションでは待ち続けてしまう。
const INITIAL_TILES_OVERLAY_MAX_MS = 6000;
// 面で塗るレイヤー（気象庁ナウキャスト系のラスタ・格子塗り・標高図）の不透明度。
// 面は「どこか」を示すもので、下の道路・地名が読めなくなると経路の判断ができない。
// 濃さはレイヤーごとに決めず1つの値を共有する——面が重なったときの濃さは重なりの数で
// 決まるべきで、レイヤーごとの主張の強さで決まると、何が上に乗っているかを読めなくなる。
const AREA_LAYER_OPACITY = 0.32;
const GSI_RELIEF_SOURCE_ID = "gsi-relief";
const GSI_RELIEF_LAYER_ID = "gsi-relief-raster";
const LANDCOVER_SOURCE_ID = "landcover";
const LANDCOVER_LAYER_ID = "landcover-raster";
// 土地被覆ラスタの帰属表示。路面タイルへ焼き込んだ割合（ROAD_TILE_ATTRIBUTION）と同じ
// 出典だが、こちらはソースが別のため独立して出す必要がある。
const LANDCOVER_ATTRIBUTION =
  '土地被覆: <a href="https://livingatlas.arcgis.com/landcover/" target="_blank" rel="noreferrer">Esri, Impact Observatory, Microsoft</a> (CC BY 4.0)';
// 動的気象レイヤー（風・降水）のsource/layer id。要素id×ソース×描画方式（raster/fill/
// mark）の組み合わせから機械的に決まるため、要素を追加してもここへ新しい定数を足す必要は
// ない（DYNAMIC_WEATHER_RENDERERS・ensureDynamicWeatherLayer参照）。sourceを分けることで
// 「1グループ=複数の名前付きソース」を表現できる（単一ソースのグループは"main"という
// 1キーだけを持つ）。
/** 気象庁タイル要素のズーム範囲。値は`backend/app/domain/jma_tile_specs.py`が配信元仕様
 * （`zoomUse`・`maxNativeZoom`）から導出したものを生成物経由で受け取る——ここで数値を
 * 手書きすると、配信元が実データを持たないズームを指してしまう（[T633]）。 */
function jmaZoomRange(elementId: keyof typeof jmaTileConfig): { minzoom: number; maxzoom: number } {
  const spec = jmaTileConfig[elementId];
  return { minzoom: spec.min_zoom, maxzoom: spec.max_zoom };
}

export function dynamicWeatherIds(
  id: DynamicWeatherLayerId,
  source: DynamicWeatherSourceId,
  sub: "raster" | "fill" | "mark" | "vector",
) {
  const base = `region-dynamic-weather-${id}-${source}-${sub}`;
  return { sourceId: base, layerId: `${base}-main`, iconId: `${base}-icon` };
}
// 空のFeatureCollection（初期化時のsourceプレースホルダ、データ未取得の間の仮の初期値）。
const EMPTY_FEATURE_COLLECTION: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
// exportはテスト専用（MapView.layerOps.test.ts）。
export const ROAD_TILE_SOURCE_ID = "region-road-surface-tiles";
export const ROAD_TILE_LAYER_ID = "region-road-surface-tiles-line";
// 「道路の種類」は路面と同じソース上の独立レイヤー。1本の線へ複数の意味を載せず、
// 同時表示は並列トラック（applyRoadMaterialTrackOffsets）で分ける。
// exportはテスト専用（MapView.layerOps.test.ts）。
export const ROAD_TYPE_LAYER_ID = "region-road-type-line";
// クリックして詳細を見ている道の強調。路面タイルのfeature-state（promoteIdで
// osm_way_idがfeature.idへ昇格済み）だけで塗るため、専用のソースも取得も増えない。
// exportはテスト専用（MapView.layerOps.test.ts）。
export const ROAD_INSPECT_LAYER_ID = "region-road-inspect-line";
// 専用way値配信軸（「評価軸」グループの風・勾配等）のMapLibre layer idは
// axisLayers.ts: dedicatedWayValueLineLayerId が軸idから導出する。ROAD_TILE_SOURCE_ID/
// ROAD_TILE_SOURCE_LAYERを共有する独立レイヤー（designation/tunnel/onewayと同じ構成）だが、
// 色分けはタイルのプロパティではなくsetFeatureState経由の値
// （dedicatedWayValueColorExpression、dedicatedWayValueLayer.ts）を読む点が異なる。
export const DESIGNATION_LAYER_ID = "region-designation-line";
// exportはテスト専用（MapView.layerOps.test.ts）。
export const TUNNEL_LAYER_ID = "region-tunnel-line";
export const ONEWAY_LAYER_ID = "region-oneway-line";
const ACCIDENT_TILE_SOURCE_ID = "region-accidents";
const ACCIDENT_LAYER_ID = "region-accidents-circle";
const POI_TILE_SOURCE_ID = "region-poi-tiles";
export const STOP_POI_LAYER_ID = "region-stop-poi-circle";
export const SUPPLY_POI_LAYER_ID = "region-supply-poi-circle";
// 線レイヤーの太さは意味を運ばない（全レイヤー共通の規約、roadFilterAxes.tsの冒頭参照）。
// exportはテスト専用（MapView.layerOps.test.ts）。
export const DEFAULT_ROAD_LINE_WIDTH = 3;
// 軸がopacityExpressionを持たない万一のフォールバック（実運用では両軸とも持つため通らない、
// applyRoadLayerState参照）。
const DEFAULT_ROAD_LINE_OPACITY = 0.8;
// road_surfaceの1次「素材」線レイヤー（道路種別/路面の合成ROAD_TILE_LAYER_ID・自転車
// インフラ・指定路線）は同じ道路ジオメトリ上に重なる独立レイヤーのため、複数を同時に
// ONにすると後から描画されたレイヤーが前のレイヤーを完全に覆い隠してしまう。line-offsetで
// 道路と平行な複数トラックへ横並びに分離する（applyRoadMaterialTrackOffsets参照）。
// トラック間隔はline-width（3px）の半分弱ずつ重なる値にしてある（重なりは色の切り替わりと
// して視認できる範囲に収まり、完全な塗り潰しにはならない）。
// exportはテスト専用（MapView.layerOps.test.ts）。
export const MATERIAL_TRACK_OFFSET_STEP = 2;
export const ROAD_MATERIAL_TRACK_LAYER_IDS = [
  ROAD_TILE_LAYER_ID,
  ROAD_TYPE_LAYER_ID,
  DESIGNATION_LAYER_ID,
  TUNNEL_LAYER_ID,
  ONEWAY_LAYER_ID,
] as const;
// ramp軸（車の圧迫感・停止密度・事故密度等、axisLayers.ts）は「推定」グループのメンバーで、
// いずれも同じroad_surfaceソース上の独立レイヤーとして重ねて描画される。2次は太く半透明な
// 「下敷き」、1次（designation等）は細くくっきりした「上書き」として重ねることで、下に
// 赤い区間があってもその上に事故地点の点や道路種別の線が乗って見えるようにする（描画順序は
// STATIC_OVERLAY_LAYERS参照。1次より下・road_surfaceより上に置く）。
// 幅は1次「素材」線が全部ONになったときの最大帯幅（トラック数×オフセット間隔＋自身の
// 太さ）から式で算出する。この式にすることで、上記2定数（トラック本数・オフセット間隔）の
// 変更に自動で追従する。
// exportはテスト専用（MapView.layerOps.test.ts）。
export const SECONDARY_AXIS_CASING_WIDTH =
  (ROAD_MATERIAL_TRACK_LAYER_IDS.length - 1) * MATERIAL_TRACK_OFFSET_STEP + DEFAULT_ROAD_LINE_WIDTH;
export const SECONDARY_AXIS_CASING_OPACITY = 0.45;
// 詳細を見ている道の強調。線そのものの色分け（評価・分類）と混ざらないよう、どの軸の
// 配色にも使っていない色を太く薄く敷く——上に元の線が乗ったままになり、何の道かは
// 引き続き色で読める。対象はタイルへ焼き込み済みの`osm_way_id`で1本へ絞る
// （どのタイルが読み込まれていても同じ式で当たる）。
const ROAD_INSPECT_COLOR = "#f59e0b";
const ROAD_INSPECT_WIDTH = 10;
const ROAD_INSPECT_OPACITY = 0.55;

// 路面・道路の種類レイヤーの初期化直後の仮の色（applyRoadLayerStateが呼び出し直後に必ず
// 実際の値へ上書きする、placeholder的な役割のみ）。
const ROAD_LINE_NEUTRAL_COLOR = "#9ca3af";

// 路面・道路の種類レイヤーの色分け式は軸ごとに固定（roadFilterAxes.ts）、
// ルートレイヤー（風・勾配）の色分け式はモード定義（routeStyleModes.ts）から取得する。
// ルート側は以降のモード切替もsetPaintProperty/setFilterによる式の差し替えのみ（路面タイルには
// surface_good/surface/highwayが、ルートのsegmentsにはaxis_difficulties（axis_id→difficultyの
// 汎用dict）・material_values（材料id→値の汎用dict）がすべて入っているため再取得は不要）。

/** レイヤーが無ければ追加し、既にあれば**spec側の設定をすべて再適用する**。
 *
 * ensure系が「既にあれば何もしない」で早期returnすると、addLayer時の値がそのまま固定され、
 * 後から入力（軸カタログ由来の色式・しきい値由来のfilter・サイズ曲線）が変わっても追随
 * しない。追加と再適用を同じspecから行うことで、「色は追随するのにfilterだけ古い」という
 * 片側だけの取り残しが起こりえない形にする——ensure関数ごとに再適用を書く形だと、
 * 新しいプロパティを足したときに書き足し忘れても何も落ちない。
 *
 * `visibility`だけは再適用しない。specが持つのは追加時の初期値で、実際の表示ON/OFFは
 * `setStaticOverlayVisibility`等が別に管理する状態のため、上書きすると利用者の選択が消える。
 *
 * `filter`は**どちらが持ち主かをspec側が宣言できない**——「キーが無い」が
 * 「自分の持ち物だが今は条件なし」と「外側が管理しているので触るな」の両方を意味しうる。
 * 呼び出し側が`specOwnsFilter`で答える（必須引数にしてあるのは、レイヤーを足すときに
 * その場で答えさせるため）。`false`のレイヤーは`setStaticOverlayFilters`が凡例の
 * ON/OFFから組み立てて与えており、ここで触ると利用者の絞り込みが巻き戻る。
 */
export function ensureLayerFromSpec(
  map: MapLibreMap,
  spec: maplibregl.AddLayerObject,
  { specOwnsFilter }: { specOwnsFilter: boolean },
) {
  if (!map.getLayer(spec.id)) {
    map.addLayer(spec);
    return;
  }
  const withProps = spec as unknown as {
    paint?: Record<string, unknown>;
    layout?: Record<string, unknown>;
    filter?: unknown;
  };
  for (const [name, value] of Object.entries(withProps.paint ?? {})) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.setPaintProperty(spec.id, name, value as any);
  }
  for (const [name, value] of Object.entries(withProps.layout ?? {})) {
    if (name === "visibility") continue;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.setLayoutProperty(spec.id, name, value as any);
  }
  // filterはraster/background/hillshadeでは設定できない（MapLibreがstyle検証で弾く）。
  // 持ち主のときは、specがfilterキーを失った場合（しきい値がnullへ変わった等）に
  // undefinedで明示的に外す——残しておくと絞り込みだけが古い条件のまま効き続ける。
  const canHaveFilter = spec.type !== "raster" && spec.type !== "background" && spec.type !== "hillshade";
  if (specOwnsFilter && canHaveFilter) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.setFilter(spec.id, (withProps.filter ?? undefined) as any);
  }
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
      tiles: [`${tileBaseUrl()}${GSI_RELIEF_TILE_PATH}`],
      tileSize: 256,
      maxzoom: GSI_RELIEF_MAX_ZOOM,
      attribution: GSI_RELIEF_ATTRIBUTION,
    });
    map.addLayer({
      id: GSI_RELIEF_LAYER_ID,
      type: "raster",
      source: GSI_RELIEF_SOURCE_ID,
      paint: { "raster-opacity": AREA_LAYER_OPACITY },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 土地被覆ラスタ。標高図と同じ「地域に固定・時間で変わらない面」で、登録も同じく一度だけ
// 行いvisibilityの切替で表示・非表示する。元データの分解能を超えるズームはMapLibreが
// 拡大して見せる（maxzoomより上を要求しない）。
function ensureLandcoverLayer(map: MapLibreMap) {
  const applyData = () => {
    if (map.getSource(LANDCOVER_SOURCE_ID)) return;
    map.addSource(LANDCOVER_SOURCE_ID, {
      type: "raster",
      tiles: [landcoverTileUrl()],
      tileSize: 256,
      minzoom: LANDCOVER_TILE_MIN_ZOOM,
      maxzoom: LANDCOVER_TILE_MAX_ZOOM,
      attribution: LANDCOVER_ATTRIBUTION,
    });
    map.addLayer({
      id: LANDCOVER_LAYER_ID,
      type: "raster",
      source: LANDCOVER_SOURCE_ID,
      paint: { "raster-opacity": AREA_LAYER_OPACITY },
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 気象庁 降水ナウキャストを含む動的気象レイヤーのソース/レイヤー登録・状態反映は、
// 風の矢印・降水延長予報と共通の汎用関数（ensureDynamicWeatherLayer/
// applyDynamicWeatherState）へ集約されている。定義は本ファイル後半、アイコン生成・色/
// サイズ式が出揃った箇所（DYNAMIC_WEATHER_RENDERERS参照）にある。

// 風の矢印。矢印アイコンのCanvas 2D描画本体（createWindArrowIcon等、MapLibre/DOM以外に
// 依存しない純粋な幾何計算）はwindArrowIcon.tsへ分離済み。ここではMapLibre側の表現
// （icon-rotate・icon-size・icon-color等）に関わる定数・式のみを持つ。ほぼ無風でも
// 矢印を出すと違和感があるため、「無風」と呼べる範囲までは閾値未満としてfilterで
// 非表示にする（関東でよく起きる1m/s未満の弱風は無風ではないため、この範囲を非表示に
// すると矢印が全滅しセル塗りと組み合わせても何も描画されないように見えることに注意）。
// アイコンサイズ（風速→スケール倍率）。最低スケールを一定以上に確保しないと、無風閾値
// ぎりぎりの矢印がほぼ最小サイズのままで目立たない。最低〜最大スケールの幅を広く取るほど、
// icon-sizeによる一様スケールが「長さで風速がわかる」度合いを強める
// （色のグラデーションは別レイヤーの役割、WIND_COLOR_SCALE_EXPRESSION参照）。
const WIND_ICON_MIN_SCALE = 0.9;
const WIND_ICON_MAX_SCALE = 2.6;
// icon-halo-*（SDFアイコンの縁取りpaintプロパティ）用の色・幅。主層と別レイヤーにしない
// ため、地図の背景色に関わらず衝突判定の対象は主層のみで縁取りは必ず追従する。
const WIND_ICON_HALO_COLOR = "rgba(31, 41, 55, 0.85)";
const WIND_ICON_HALO_WIDTH_PX = 1.5;
// 微風=水色→ロードバイクで走行が難しい強風域=濃い赤の連続グラデーション（ビューフォート
// 風力階級準拠、windLayer.ts: WIND_SPEED_COLOR_STOPSのコメント参照）。矢印のicon-colorと
// 地図チップの凡例（page.tsx）の2箇所で同じ配色を使うため、生データはwindLayer.tsを
// 単一の情報源として持ち、MapLibre補間式への組み立てだけここで行う。
const WIND_COLOR_SCALE_EXPRESSION = [
  "interpolate",
  ["linear"],
  ["to-number", ["get", "speed"]],
  ...WIND_SPEED_COLOR_STOPS.flatMap((stop) => [stop.speedMs, stop.color]),
] as unknown as maplibregl.ExpressionSpecification;

// 降水延長予報（gridFill、格子セルを指定色で塗る）のfill-color。PRECIPITATION_COLOR_STOPS
// （precipitationNowcast.ts、地図チップの凡例と単一の情報源）をMapLibre補間式へ組み立てる。
const PRECIPITATION_COLOR_SCALE_EXPRESSION = [
  "interpolate",
  ["linear"],
  ["to-number", ["get", "mmPerHour"]],
  ...PRECIPITATION_COLOR_STOPS.flatMap((stop) => [stop.mmPerHour, stop.color]),
] as unknown as maplibregl.ExpressionSpecification;

// 洪水キキクルのline-color。配信元のフィーチャーが持つ`level`
// プロパティ（1〜4）をRISK_LEVEL_COLORS（riskMap.ts、土砂・大雨・浸水の3種と共通の
// 危険度配色）へそのままmatchする。level=0・未設定のフィーチャー（平常時の基準線）は
// DYNAMIC_WEATHER_RENDERERS.floodRiskのminValueToShowフィルタで描画対象から除外される
// ため、フォールバック値（levelがmatchのどれにも該当しない場合）は実際には使われないが、
// MapLibreのmatch式は仕様上フォールバックが必須のためRISK_LEVEL_COLORS[0]（level0の色）を
// 割り当てておく。
const FLOOD_RISK_LINE_COLOR_EXPRESSION = [
  "match",
  ["to-number", ["get", "level"]],
  1,
  RISK_LEVEL_COLORS[1].color,
  2,
  RISK_LEVEL_COLORS[2].color,
  3,
  RISK_LEVEL_COLORS[3].color,
  4,
  RISK_LEVEL_COLORS[4].color,
  RISK_LEVEL_COLORS[0].color,
] as unknown as maplibregl.ExpressionSpecification;

// 河川の危険情報という性質上、低ズームでは目立たせすぎず、拡大するほど個々の河川区間を
// 追いやすいよう太くする（JMA公式サイトのzoom依存weight式を単純化した近似値）。
const FLOOD_RISK_LINE_WIDTH_EXPRESSION = [
  "interpolate",
  ["linear"],
  ["zoom"],
  6,
  1.5,
  10,
  3,
  14,
  5,
] as unknown as maplibregl.ExpressionSpecification;

/** 動的気象レイヤー1要素ぶんの描画スペック。raster/gridFill/gridMarkのうち実際に使う
 * ものだけを持つ（例: windVectorはgridMarkのみ、precipitationNowcastはraster+gridFillの
 * 2つを併せ持ち、選択中の時刻が60分以内かどうかでpage.tsx側がどちらのkindのペイロードを
 * 渡すか決める。表示層は常にkindを見るだけで、この2レイヤーの扱いに差は無い）。 */
interface DynamicWeatherRasterSpec {
  placeholderTileUrl: string;
  opacity: number;
  minzoom?: number;
  maxzoom?: number;
  attribution?: string;
}

interface DynamicWeatherFillSpec {
  valueProperty: string;
  colorExpression: maplibregl.ExpressionSpecification;
  opacity: number;
  minValueToShow?: number;
}

interface DynamicWeatherMarkSpec {
  createIcon: () => ImageData;
  colorExpression: maplibregl.ExpressionSpecification;
  valueProperty: string;
  rotateProperty?: string;
  minScale: number;
  maxScale: number;
  maxValueForFullScale: number;
  haloColor: string;
  haloWidth: number;
  minValueToShow?: number;
}

/** 配信元のMapbox Vector Tile（.pbf）をMapLibre標準のvectorソース+lineレイヤーで
 * そのまま描画する（洪水キキクル）。gridFill/gridMarkと違い値は
 * フィーチャーのプロパティに焼き込み済みのため、feature-state・GeoJSON変換は不要——
 * source-layer名とMapLibre paint式（プロパティ参照）だけを持てばよい。 */
interface DynamicWeatherVectorSpec {
  placeholderTileUrl: string;
  sourceLayer: string;
  colorExpression: maplibregl.ExpressionSpecification;
  lineWidthExpression: maplibregl.ExpressionSpecification;
  /** フィルタ対象のプロパティ名（例: "level"）。minValueToShow未指定ならフィルタ無し。 */
  valueProperty?: string;
  minValueToShow?: number;
  minzoom?: number;
  maxzoom?: number;
  attribution?: string;
}

interface DynamicWeatherRendererSpec {
  raster?: DynamicWeatherRasterSpec;
  gridFill?: DynamicWeatherFillSpec;
  gridMark?: DynamicWeatherMarkSpec;
  vector?: DynamicWeatherVectorSpec;
}

// 1グループ（=1 DynamicWeatherLayerId）配下の名前付きソースごとの描画スペック。
// 単一ソースしか持たないグループは"main"という1キーだけを持つ。
type DynamicWeatherGroupSpec = Partial<Record<DynamicWeatherSourceId, DynamicWeatherRendererSpec>>;

// 動的気象レイヤーの描画スペック一覧（唯一の情報源）。新しい要素を追加するときはここへ
// 1エントリ足すだけでよい（dynamicWeather.ts冒頭の「1本道」コメント参照）。色・アイコン式を
// 参照するため、それらのconst定義より後（JSのconstはhoistされないため）に置く必要がある。
export const DYNAMIC_WEATHER_RENDERERS: Record<DynamicWeatherLayerId, DynamicWeatherGroupSpec> = {
  precipitationNowcast: {
    main: {
      raster: {
        // 初期化時のsourceプレースホルダ（applyDynamicWeatherStateが本物のURLへsetTilesで
        // 差し替えてからvisibility:visibleにする、ensureRoadSurfaceTileLayer等と同じ
        // 「仮の初期値」パターン。setTiles→visibility切替の順序自体は守られている）。
        // このプレースホルダURL（時刻部分が全ゼロの架空値）は、React Strict Modeの
        // 開発時二重実行（mount→cleanup→再mount）で初回payload未確定時に一瞬visible=trueに
        // なるタイミングが生じると、実際にタイルリクエストが飛びJMA側で404になりうる
        // （`next dev`限定の想定、本番ビルドではStrict Modeの二重実行が発生しないため
        // 再現しない）。表示自体は次のpayload反映で自己回復するため実害は無い。
        placeholderTileUrl: jmaPlaceholderTileUrl("nowc", "hrpns"),
        opacity: AREA_LAYER_OPACITY,
        ...jmaZoomRange("hrpns"),
        attribution: "気象庁",
      },
      gridFill: {
        valueProperty: "mmPerHour",
        colorExpression: PRECIPITATION_COLOR_SCALE_EXPRESSION,
        opacity: AREA_LAYER_OPACITY,
        minValueToShow: PRECIPITATION_NONE_THRESHOLD_MM,
      },
    },
    // 線状降水帯予測マップ。ナウキャスト/rasrf/延長予報（"main"）と独立に重畳表示する——
    // フレーム列を持たない単発スナップショットのため、共有タイムラインが「現在〜3時間先」の
    // 範囲内にあるときだけpayloadが渡る（useDynamicWeatherLayers.ts: linearRainbandVisible参照）。
    linearRainband: {
      raster: {
        placeholderTileUrl: jmaPlaceholderTileUrl("rasrf", "sjfcstmap"),
        opacity: AREA_LAYER_OPACITY,
        ...jmaZoomRange("sjfcstmap"),
        attribution: "気象庁",
      },
    },
  },
  windVector: {
    // 矢印。走行方位に依存しない風向・風速そのものの表示のみを持つ
    // （評価軸としての向かい風/追い風の強さはRouteSettingsPanel「風」の「地図で色分け」
    // ボタン[専用way値配信軸のレンズ]・地図の色分け[ルート確定後]が担う）。
    arrow: {
      gridMark: {
        createIcon: createWindArrowIcon,
        colorExpression: WIND_COLOR_SCALE_EXPRESSION,
        valueProperty: "speed",
        rotateProperty: "bearing",
        minScale: WIND_ICON_MIN_SCALE,
        maxScale: WIND_ICON_MAX_SCALE,
        maxValueForFullScale: 15,
        haloColor: WIND_ICON_HALO_COLOR,
        haloWidth: WIND_ICON_HALO_WIDTH_PX,
        minValueToShow: WIND_CALM_THRESHOLD_MS,
      },
    },
  },
  // 災害。配下の要素を名前付きソースとして同時に描画する1グループ（mapLayers.ts: "disaster"）。
  // オブジェクトのキー順がそのままMapLibreのレイヤー追加順＝重なり順になる
  // （ensureDynamicWeatherLayerがObject.entriesで走査する）ため、面（キキクル・雷・竜巻の
  // ラスタ）を下に、局所的で見落としやすい線（洪水）・点（落雷）を上に置く。ラスタ同士が
  // 重なった領域は混色になるが、危険度ゼロの領域は配信元のタイルが透明のため、平常時は
  // 配下をすべてONにしても地図の見た目は変わらない。
  disaster: {
    // キキクル（危険度分布）。ズーム範囲はjmaZoomRangeが配信元仕様から導出する。
    // 大雨は浸水・土砂双方を統合した指標のため、個別の土砂・浸水より下に置く。
    heavyRain: {
      raster: {
        placeholderTileUrl: jmaPlaceholderTileUrl("risk", "rain_mesh"),
        opacity: AREA_LAYER_OPACITY,
        ...jmaZoomRange("rain_mesh"),
        attribution: "気象庁",
      },
    },
    landslide: {
      raster: {
        placeholderTileUrl: jmaPlaceholderTileUrl("risk", "land"),
        opacity: AREA_LAYER_OPACITY,
        ...jmaZoomRange("land"),
        attribution: "気象庁",
      },
    },
    inundation: {
      raster: {
        placeholderTileUrl: jmaPlaceholderTileUrl("risk", "inund"),
        opacity: AREA_LAYER_OPACITY,
        ...jmaZoomRange("inund"),
        attribution: "気象庁",
      },
    },
    // 雷ナウキャスト・竜巻発生確度ナウキャスト。降水ナウキャストと同じbosai/jmatile/
    // data/nowc/系だが、60分より先の延長予報を持たない（MSM側に雷・竜巻に相当する
    // データが無いため）。プロダクトコード違い（thns/trns）だけの単純なrasterのみの
    // スペックで、gridFill/gridMarkは持たない。
    thunder: {
      raster: {
        placeholderTileUrl: jmaPlaceholderTileUrl("nowc", "thns"),
        opacity: AREA_LAYER_OPACITY,
        ...jmaZoomRange("thns"),
        attribution: "気象庁",
      },
    },
    tornado: {
      raster: {
        placeholderTileUrl: jmaPlaceholderTileUrl("nowc", "trns"),
        opacity: AREA_LAYER_OPACITY,
        ...jmaZoomRange("trns"),
        attribution: "気象庁",
      },
    },
    // 洪水キキクル。他3種と異なり配信元がMapbox Vector Tile（.pbf）のためvector kind
    // （riskMap.ts冒頭コメント参照）。source-layer名"flood"・プロパティ"level"（1〜4）は
    // risk.properties.xmlのvectorTileLayerStyles.floodに対応する。
    flood: {
      vector: {
        // ベクタタイルはMapLibreがWeb Worker内で取得するため、相対パスのままだとWorkerの
        // base URLに対して解決できず例外になる（regionApi.ts: roadSurfaceTileUrl等と同じ
        // 理由、riskMap.ts: tileUrlTemplateのpbf分岐参照）。DYNAMIC_WEATHER_RENDERERSは
        // モジュール読み込み時に評価される定数のため、純ロジックのみをnode環境（windowを
        // 持たない）でテストするMapView.routes.test.ts等からも本ファイルがimportされる。
        // windowが無い環境ではこのプレースホルダURLの値自体は使われないため、その場合だけ
        // 絶対URL化を諦め相対URLへ戻す（実ブラウザでは常にwindowが存在する）。
        placeholderTileUrl: jmaPlaceholderTileUrl("risk", "flood", "pbf"),
        sourceLayer: "flood",
        colorExpression: FLOOD_RISK_LINE_COLOR_EXPRESSION,
        lineWidthExpression: FLOOD_RISK_LINE_WIDTH_EXPRESSION,
        valueProperty: "level",
        // level>=1（=何らかの危険度あり）のフィーチャーだけを表示する（riskMap.ts冒頭
        // コメント「危険情報のみ」方針参照）。既存のminValueToShowフィルタ（gridFill/
        // gridMarkと共通のパターン）をそのまま流用する。
        minValueToShow: 0,
        ...jmaZoomRange("flood"),
        attribution: "気象庁",
      },
    },
    // 雷放電位置データ（落雷）。同じN3配信の雷ナウキャストと異なり、配信元が既にGeoJSON
    // （個々の落雷地点）で提供するためraster設定を持たない。geojson自体は
    // hooks/useDynamicWeatherLayers.tsが選択フレームごとに取得しstateへ持つ（他要素の
    // gridMarkと異なり、既存の格子データからの合成ではなく配信元GeoJSONをそのまま渡す）。
    // 落雷の強弱を示す値を配信元が持たないため、valueProperty（LIDEN_MARK_VALUE_PROPERTY）は
    // 常に固定値で、minScale===maxScaleによりicon-sizeはズームだけに依存する。
    liden: {
      gridMark: {
        createIcon: createLidenIcon,
        colorExpression: "#facc15" as unknown as maplibregl.ExpressionSpecification,
        valueProperty: LIDEN_MARK_VALUE_PROPERTY,
        minScale: 0.8,
        maxScale: 0.8,
        maxValueForFullScale: 1,
        haloColor: "rgba(31, 41, 55, 0.85)",
        haloWidth: 1.5,
      },
    },
  },
};

// 動的気象レイヤーのsource/レイヤーを初期化時に一度だけ追加する（GSI標高ラスタ等と同じ
// パターン）。グループ配下の各ソースについて、spec.raster/gridFill/gridMark/vectorのうち
// 実際に指定されているものだけを追加する。
// レイヤーが既に存在する場合も各paintプロパティをsetPaintPropertyで再適用する
// （addLayer時の値で固定させない）——map.setStyle()後の作り直しと、同じidへ別のgroupSpecが
// 渡された場合のどちらでも、addLayerが「既にある」で早期returnして古い見た目が残るのを防ぐ。
export function ensureDynamicWeatherLayer(
  map: MapLibreMap,
  id: DynamicWeatherLayerId,
  groupSpec: DynamicWeatherGroupSpec,
) {
  const applyData = () => {
    for (const [source, spec] of Object.entries(groupSpec)) {
      if (!spec) continue;
      if (spec.raster) {
        const { sourceId, layerId } = dynamicWeatherIds(id, source, "raster");
        if (!map.getSource(sourceId)) {
          map.addSource(sourceId, {
            type: "raster",
            tiles: [withJmaTileProtocol(spec.raster.placeholderTileUrl)],
            tileSize: 256,
            minzoom: spec.raster.minzoom,
            maxzoom: spec.raster.maxzoom,
            attribution: spec.raster.attribution,
          });
        }
        // specOwnsFilter: 動的気象レイヤーのspecが絞り込みの持ち主（外から与える経路が無い）。
        ensureLayerFromSpec(
          map,
          {
            id: layerId,
            type: "raster",
            source: sourceId,
            paint: { "raster-opacity": spec.raster.opacity },
            layout: { visibility: "none" },
          },
          { specOwnsFilter: true },
        );
      }
      if (spec.gridFill) {
        const { sourceId, layerId } = dynamicWeatherIds(id, source, "fill");
        if (!map.getSource(sourceId)) {
          map.addSource(sourceId, {
            type: "geojson",
            data: EMPTY_FEATURE_COLLECTION,
            attribution: "気象庁MSM / Open-Meteo",
          });
        }
        ensureLayerFromSpec(
          map,
          {
            id: layerId,
            type: "fill",
            source: sourceId,
            layout: { visibility: "none" },
            paint: {
              "fill-color": spec.gridFill.colorExpression,
              "fill-opacity": spec.gridFill.opacity,
            },
            // filterキー自体を「値がundefinedのまま持たせる」と、MapLibreのstyle検証が
            // 「filterには配列が必要」というエラーを出す（キーの有無ではなく値の型で
            // 判定するため）。minValueToShowが無い場合はキーごと省略する。
            ...(spec.gridFill.minValueToShow != null
              ? {
                  filter: [
                    ">",
                    ["to-number", ["get", spec.gridFill.valueProperty]],
                    spec.gridFill.minValueToShow,
                  ] as maplibregl.ExpressionSpecification,
                }
              : {}),
          },
          { specOwnsFilter: true },
        );
      }
      if (spec.gridMark) {
        const mark = spec.gridMark;
        const { sourceId, layerId, iconId } = dynamicWeatherIds(id, source, "mark");
        if (!map.hasImage(iconId)) {
          // sdf:trueで登録すると、単色シルエット画像でもicon-colorでの着色対象になる
          // （真のsigned distance fieldではなく塗りつぶし画像だが、本アイコンの表示サイズ
          // 範囲では実用上問題ない簡易的な使い方）。icon-halo-*（縁取り）paintプロパティも
          // sdf:true必須。
          map.addImage(iconId, mark.createIcon(), { sdf: true });
        }
        if (!map.getSource(sourceId)) {
          map.addSource(sourceId, {
            type: "geojson",
            data: EMPTY_FEATURE_COLLECTION,
            attribution: "気象庁MSM / Open-Meteo",
          });
        }
        // 縁取りは別レイヤーではなくicon-halo-*（主層と同じsymbolレイヤーのpaint
        // プロパティ）で表現する。別レイヤーの縁取りは、MapLibreがレイヤーの上から順に
        // シンボルを配置するため、先に置かれた主層と同位置・大きめの縁取り層が「衝突」として
        // 全て落ちる（icon-allow-overlap: falseのため）。1層にまとめれば主層自身の衝突判定
        // （密なズームで格子点を間引く）に縁取りが自動的に追従する。
        ensureLayerFromSpec(
          map,
          {
            id: layerId,
            type: "symbol",
            source: sourceId,
            layout: {
              "icon-image": iconId,
              "icon-rotate": mark.rotateProperty ? ["to-number", ["get", mark.rotateProperty]] : 0,
              "icon-rotation-alignment": mark.rotateProperty ? "map" : "viewport",
              "icon-allow-overlap": false,
              "icon-ignore-placement": false,
              // 長さ・太さをまとめてスケールする（アイコン全体の一様拡大）。
              "icon-size": zoomAndPropertyIconSizeExpression(
                mark.valueProperty,
                mark.minScale,
                mark.maxScale,
                mark.maxValueForFullScale,
                1,
              ),
              visibility: "none",
            },
            paint: {
              "icon-color": mark.colorExpression,
              "icon-opacity": 1,
              "icon-halo-color": mark.haloColor,
              "icon-halo-width": mark.haloWidth,
            },
            ...(mark.minValueToShow != null
              ? {
                  filter: [
                    ">",
                    ["to-number", ["get", mark.valueProperty]],
                    mark.minValueToShow,
                  ] as maplibregl.ExpressionSpecification,
                }
              : {}),
          },
          { specOwnsFilter: true },
        );
      }
      if (spec.vector) {
        const vector = spec.vector;
        const { sourceId, layerId } = dynamicWeatherIds(id, source, "vector");
        if (!map.getSource(sourceId)) {
          map.addSource(sourceId, {
            type: "vector",
            tiles: [withJmaTileProtocol(vector.placeholderTileUrl)],
            minzoom: vector.minzoom,
            maxzoom: vector.maxzoom,
            attribution: vector.attribution,
          });
        }
        ensureLayerFromSpec(
          map,
          {
            id: layerId,
            type: "line",
            source: sourceId,
            "source-layer": vector.sourceLayer,
            paint: {
              "line-color": vector.colorExpression,
              "line-width": vector.lineWidthExpression,
            },
            layout: { visibility: "none" },
            // gridFill/gridMarkと同じ理由（上記参照）でminValueToShow未設定時はfilterキー
            // 自体を省略する。
            ...(vector.minValueToShow != null && vector.valueProperty
              ? {
                  filter: [
                    ">",
                    ["to-number", ["get", vector.valueProperty]],
                    vector.minValueToShow,
                  ] as maplibregl.ExpressionSpecification,
                }
              : {}),
          },
          { specOwnsFilter: true },
        );
      }
    }
  };
  runWhenStyleReady(map, applyData);
}

// payload（page.tsx側が各要素のデータ層関数から計算した値）を反映する。グループ配下の
// 各ソースについて、visibleとpayloadのどちらか一方でも欠けていれば非表示のまま（フェッチ
// 未完了・取得失敗時、あるいは選択時刻がそのソースのデータ範囲外で「描画しない」場合に、
// 古いフレームが一瞬見えるのを防ぐ）。payload.kindがそのソースのspecの複数サブレイヤー
// （precipitationNowcast.mainのraster/gridFill等）のどれと対応するかだけを見て、対応しない
// サブレイヤーは常に非表示にする（=同時に両方は出ない）。ソースをまたいだ複数payloadの
// 同時表示（precipitationNowcastのmain+linearRainband等）は、グループ内の別ソースとして
// 独立にvisible/payloadを持つことで実現する（このループ自体は各ソースを独立に処理するだけ）。
// setTiles()は同じURLを渡しても無条件にソースをリロードし、読み込み済みのタイルを
// 破棄して取得し直す（ラスタは特にPNGデコード・GPUテクスチャアップロードのコストが
// 大きい）。dynamicWeatherは風・降水・雷等いずれか1要素の更新だけでも新しいオブジェクト
// 参照になり、applyDynamicWeatherStateは全グループぶん毎回呼ばれるため、URLが前回から
// 変わっていないソースまで巻き添えで再読み込みされる。ソースごとに前回適用したURLを
// 覚えておき、変化が無ければsetTilesを呼ばない。
const lastAppliedTileUrl = new WeakMap<object, string>();

// この関数を通るのは動的気象レイヤー（JMAタイル）のソースだけのため、ここで
// jmatile://スキームを付ける（jmaTileProtocol.tsが在否インデックスを見て、空と分かって
// いるタイルをネットワークへ出さずに透明タイルで返す）。
function setTilesIfChanged(source: maplibregl.RasterTileSource | maplibregl.VectorTileSource, url: string): void {
  const tileUrl = withJmaTileProtocol(url);
  if (lastAppliedTileUrl.get(source) === tileUrl) return;
  lastAppliedTileUrl.set(source, tileUrl);
  source.setTiles([tileUrl]);
}

// gridFill/gridMark（GeoJSONSource）向けの同型ガード。setData()はネットワーク取得こそ
// 無いが、渡したデータをワーカーへ送り直しインデックスを再構築させる点はsetTilesと同じ
// 「無条件に再構築」挙動のため揃えておく。内容比較にJSON.stringifyを使うのは、
// payloadが都度新しいオブジェクト参照で計算される（風グリッド・落雷位置等、都度数十〜
// 数百点程度）ため参照比較では意味が無く、かつこの規模なら文字列化のコストは無視できる
// ため。
const lastAppliedGeojson = new WeakMap<object, string>();

function setDataIfChanged(source: GeoJSONSource, geojson: GeoJSON.GeoJSON): void {
  const serialized = JSON.stringify(geojson);
  if (lastAppliedGeojson.get(source) === serialized) return;
  lastAppliedGeojson.set(source, serialized);
  source.setData(geojson);
}

export function applyDynamicWeatherState(
  map: MapLibreMap,
  id: DynamicWeatherLayerId,
  groupSpec: DynamicWeatherGroupSpec,
  groupState: DynamicWeatherGroupState | undefined,
) {
  runWhenStyleReady(map, () => {
    ensureDynamicWeatherLayer(map, id, groupSpec);
    for (const [source, spec] of Object.entries(groupSpec)) {
      if (!spec) continue;
      const state = groupState?.[source];
      const visible = state?.visible ?? false;
      const payload = state?.payload;
      if (spec.raster) {
        const { sourceId, layerId } = dynamicWeatherIds(id, source, "raster");
        if (payload?.kind === "rasterTile") {
          const rasterSource = map.getSource(sourceId) as maplibregl.RasterTileSource | undefined;
          if (rasterSource) setTilesIfChanged(rasterSource, payload.tileUrlTemplate);
        }
        setLayerVisibility(map, layerId, visible && payload?.kind === "rasterTile");
      }
      if (spec.gridFill) {
        const { sourceId, layerId } = dynamicWeatherIds(id, source, "fill");
        if (payload?.kind === "gridFill") {
          const fillSource = map.getSource(sourceId) as GeoJSONSource | undefined;
          if (fillSource) setDataIfChanged(fillSource, payload.geojson);
        }
        setLayerVisibility(map, layerId, visible && payload?.kind === "gridFill");
      }
      if (spec.gridMark) {
        const { sourceId, layerId } = dynamicWeatherIds(id, source, "mark");
        if (payload?.kind === "gridMark") {
          const markSource = map.getSource(sourceId) as GeoJSONSource | undefined;
          if (markSource) setDataIfChanged(markSource, payload.geojson);
        }
        setLayerVisibility(map, layerId, visible && payload?.kind === "gridMark");
      }
      if (spec.vector) {
        const { sourceId, layerId } = dynamicWeatherIds(id, source, "vector");
        if (payload?.kind === "vectorTile") {
          const vectorSource = map.getSource(sourceId) as maplibregl.VectorTileSource | undefined;
          if (vectorSource) setTilesIfChanged(vectorSource, payload.tileUrlTemplate);
        }
        setLayerVisibility(map, layerId, visible && payload?.kind === "vectorTile");
      }
    }
  });
}

// 路面もGSI標高ラスタと同じ考え方で、地図初期化時に一度だけベクタタイルのソース/レイヤーを
// 追加し、以降はvisibilityの切替・setPaintProperty/setFilterのみで表示・非表示・見た目を
// 変える。標高ラスタの直後に追加することで、標高の上・ルート系レイヤーの下に描画される。
// paintの初期値は仮の中立値（applyRoadLayerStateが呼び出し直後に必ず実際の値へ上書きする）。
function ensureRoadSurfaceTileLayer(map: MapLibreMap) {
  const applyData = () => {
    if (map.getSource(ROAD_TILE_SOURCE_ID)) return;
    map.addSource(ROAD_TILE_SOURCE_ID, {
      type: "vector",
      tiles: [roadSurfaceTileUrl()],
      minzoom: ROAD_TILE_MIN_ZOOM,
      maxzoom: ROAD_TILE_MAX_ZOOM,
      // way_id→wind_drag_ratio配信層（評価軸グループとしての風）がMapLibreの
      // setFeatureStateでこのソースの地物へ後から値を差し込むために必要。MVTのフィーチャーは
      // 既定では安定したidを持たないため、既存のosm_way_idプロパティ（区間インスペクタ用に
      // 元から焼き込み済み、_ROAD_SURFACE_TILE_MVT_SQL参照）をfeature.idへ昇格させる
      // （バックエンド側のタイル内容・世代は変更不要）。
      promoteId: { [ROAD_TILE_SOURCE_LAYER]: "osm_way_id" },
      attribution: ROAD_TILE_ATTRIBUTION,
    });
    for (const layerId of [ROAD_TILE_LAYER_ID, ROAD_TYPE_LAYER_ID]) {
      map.addLayer({
        id: layerId,
        type: "line",
        source: ROAD_TILE_SOURCE_ID,
        "source-layer": ROAD_TILE_SOURCE_LAYER,
        paint: {
          "line-color": ROAD_LINE_NEUTRAL_COLOR,
          "line-width": DEFAULT_ROAD_LINE_WIDTH,
          "line-opacity": DEFAULT_ROAD_LINE_OPACITY,
          // 初期値は0（applyRoadMaterialTrackOffsetsが可視化のたびに実際の値へ上書きする）
          "line-offset": 0,
        },
        layout: { visibility: "none" },
      });
    }
    map.addLayer({
      id: ROAD_INSPECT_LAYER_ID,
      type: "line",
      source: ROAD_TILE_SOURCE_ID,
      "source-layer": ROAD_TILE_SOURCE_LAYER,
      paint: {
        "line-color": ROAD_INSPECT_COLOR,
        "line-width": ROAD_INSPECT_WIDTH,
        "line-opacity": ROAD_INSPECT_OPACITY,
      },
      // 対象はfilterで1本へ絞る（タイルへ焼き込み済みのosm_way_idで引く）。表示のたびに
      // 該当wayを選び直す（applyInspectedWay）。
      filter: ["==", ["get", "osm_way_id"], -1],
      layout: { visibility: "none" },
    });
  };
  runWhenStyleReady(map, applyData);
}

// 専用のway_id→動的値配信層を持つ軸（風・勾配）のensure/apply/clearは、レイヤーID・色式・
// feature-stateキーだけが違う同型の関数を軸ごとに用意するのではなく、makeEnsureAxisRampLayer
// （ramp軸向け、上記）と同じ「1ファクトリ+N呼び出し」パターンへ統一する。
//
// way_id→値配信層。designation/tunnel/onewayと同じくROAD_TILE_
// SOURCE_ID/ROAD_TILE_SOURCE_LAYERを共有する独立レイヤーだが、色分けはタイルの
// プロパティではなくsetFeatureState経由の値（applyAxisFeatureStateValues参照）を読む。
// ensureRoadSurfaceTileLayerを先に呼び、promoteId付きのsourceが確実に存在する状態で
// レイヤーを追加する（designation等の既存レイヤーもこのソースへ依存する順序を暗黙に
// 仮定しており、それと同じ前提）。colorExpressionはdedicatedWayValueDisplays
// （軸カタログのmap_value_thresholds、実行時フェッチで後から変わりうる）に
// 依存するため、レイヤーが既に存在する場合もsetPaintPropertyで再適用する
// （初回作成時の値のまま固定させず、フェッチ完了後の値を反映させるため）。
function makeEnsureDedicatedWayValueLayer(layerId: string, colorExpression: unknown[]): (map: MapLibreMap) => void {
  return (map: MapLibreMap) => {
    ensureRoadSurfaceTileLayer(map);
    const applyData = () => {
      // specOwnsFilter: 専用way値レイヤーはSTATIC_FILTER_AXESの対象外で、外から絞り込みを
      // 与える経路が無い。
      ensureLayerFromSpec(
        map,
        {
          id: layerId,
          type: "line",
          source: ROAD_TILE_SOURCE_ID,
          "source-layer": ROAD_TILE_SOURCE_LAYER,
          paint: {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            "line-color": colorExpression as any,
            "line-width": DEFAULT_ROAD_LINE_WIDTH,
          },
          layout: { visibility: "none" },
        },
        { specOwnsFilter: true },
      );
    };
    runWhenStyleReady(map, applyData);
  };
}

// useDedicatedWayValues（hooks）が取得した{way_id: 値}をMapLibreのsetFeatureStateで
// 地物へ差し込む。パン・ズームで
// 表示範囲が変わり、直前に取得した一部のway_idが最新の応答に含まれなくなっても、
// 明示的なremoveFeatureStateは行わない（windLayer.ts: mergeWindGridKeepingStaleと同じ
// 判断——古い値が多少残る方が、穴が開いたように見えるより実用上マシという方針を踏襲する。
// 値そのものはbackend側のRedis TTLの範囲でしか新鮮さを保証しないため、古い値が長時間
// 残り続けることはない）。featureStateKeyだけが軸ごとに異なる（
// dedicatedWayValueLayer.ts: dedicatedWayValueFeatureStateKey）。
// exportはテスト専用（MapView.layerOps.test.ts）。
export function applyAxisFeatureStateValues(
  map: MapLibreMap,
  featureStateKey: string,
  values: ReadonlyMap<number, number>,
) {
  if (!map.getSource(ROAD_TILE_SOURCE_ID)) return;
  values.forEach((value, wayId) => {
    map.setFeatureState(
      { source: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER, id: wayId },
      { [featureStateKey]: value },
    );
  });
}

/** 専用way値配信軸（評価軸グループの風・勾配等、視界内の全道路への一律色分け）が
 * 終了する瞬間（どの軸も表示されなくなる瞬間——ルート確定・
 * 手動OFFのいずれも含む）に、それまでsetFeatureStateで差し込んだ全道路ぶんの値を
 * 明示的にクリアする。上のapplyAxisFeatureStateValuesは（enabledのままパン・ズームで
 * 一部way_idが新しい応答へ含まれなくなる通常のケース向けに）意図的に古い値を残す設計だが、
 * ルート確定後はルート以外の道路を無色に戻す必要がある——レイヤー自体はvisibility:noneで
 * 非表示になるため視覚上は問題ないが、値そのものも消しておく（再度ONにしたときに
 * 一瞬だけ古い値がちらつくのを防ぐ副次効果もある）。removeFeatureStateはsource/
 * sourceLayer単位で全キーをまとめて消す（MapLibreの仕様）ため、風・勾配どちらの
 * 終了判定からでも同じこの1関数を呼べばよい（feature-stateキーごとの個別クリアは
 * 元々できない）。 */
// exportはテスト専用（MapView.layerOps.test.ts）。
export function clearRoadTileFeatureState(map: MapLibreMap) {
  if (!map.getSource(ROAD_TILE_SOURCE_ID)) return;
  map.removeFeatureState({ source: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER });
}

/** 上記clearRoadTileFeatureStateを呼ぶべきかどうかの判定条件（専用way値配信軸が
 * 1つも表示されていないか）を、下のuseEffect内のif文から純粋関数として切り出したもの。
 * removeFeatureStateがsource/sourceLayer単位で全キーを一括で消すMapLibre仕様のため、
 * 表示中の軸が1つでも残っている間にクリアするとその軸の色分けまで巻き添えで消える。
 * 軸の件数に依存しない全称判定にしてあり、3件目の軸が公開されても条件は正しいまま。 */
export function shouldClearDedicatedWayValueFeatureState(
  dedicatedWayValueVisibility: Readonly<Record<string, boolean>>,
): boolean {
  return !Object.values(dedicatedWayValueVisibility).some(Boolean);
}

/** 詳細を見ている道を1本だけ強調する。nullで強調を消す。レイヤーがまだ無ければ何もしない
 * （作り直しの途中でも落ちないようにする）。exportはテスト専用
 * （MapView.layerOps.test.ts）。 */
export function applyInspectedWay(map: MapLibreMap, osmWayId: number | null) {
  if (!map.getLayer(ROAD_INSPECT_LAYER_ID)) return;
  setLayerVisibility(map, ROAD_INSPECT_LAYER_ID, osmWayId !== null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  map.setFilter(ROAD_INSPECT_LAYER_ID, ["==", ["get", "osm_way_id"], osmWayId ?? -1] as any);
}

// 「道路情報」の各軸（路面の種類・道路の種類）は、それぞれ独立した線レイヤーとして描く。
// 1本の線へ両方の意味を載せると色チャンネルの取り合いになり、同じレイヤーの色の意味が
// もう一方のON/OFFで入れ替わる。同時にONのときは並列トラック（applyRoadMaterialTrackOffsets）
// が横へ分離する。太さ・線種は意味を運ばない（roadFilterAxes.tsの冒頭参照）。
function applyRoadLayerState(
  map: MapLibreMap,
  showRoadSurface: boolean,
  showRoadType: boolean,
  hiddenKeysByAxis: Record<RoadFilterAxisId, readonly string[]>,
) {
  runWhenStyleReady(map, () => {
    ensureRoadSurfaceTileLayer(map);
    for (const [layerId, axisId, visible] of [
      [ROAD_TILE_LAYER_ID, ROAD_SURFACE_AXIS_ID, showRoadSurface],
      [ROAD_TYPE_LAYER_ID, ROAD_TYPE_AXIS_ID, showRoadType],
    ] as const) {
      setLayerVisibility(map, layerId, visible);
      if (!visible) continue;
      const axis = getRoadFilterAxis(axisId);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map.setPaintProperty(layerId, "line-color", axis.colorExpression as any);
      map.setPaintProperty(layerId, "line-width", DEFAULT_ROAD_LINE_WIDTH);
      map.setPaintProperty(
        layerId,
        "line-opacity",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (axis.opacityExpression ?? DEFAULT_ROAD_LINE_OPACITY) as any,
      );
      const filter = buildCombinedLegendFilterExpression([
        { legend: axis.legend, hiddenKeys: hiddenKeysByAxis[axis.id] ?? [] },
      ]);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map.setFilter(layerId, filter as any);
    }
  });
}

// road_surfaceの1次「素材」線レイヤー（道路種別/路面の合成ROAD_TILE_LAYER_ID・指定路線等）を
// 並列トラックへ分離するオフセット計算。定数
// （MATERIAL_TRACK_OFFSET_STEP/ROAD_MATERIAL_TRACK_LAYER_IDS）・下敷き幅との連動理由は
// 上部のDEFAULT_ROAD_LINE_WIDTH直後のコメント参照。
// 現在ONの素材レイヤー集合から各レイヤーのline-offsetを計算して適用する。ON中のものだけを
// 対称に割り付ける（1件→0、2件→±1.5、3件→-3/0/+3）ため、どれかをOFFにすると残りが
// 自動で中央（実際の道路の位置）へ寄り直す。OFF中のレイヤーもoffsetを0へ戻しておき、
// 次にONにしたときに古いオフセット値が一瞬残らないようにする。
// exportはテスト専用（MapView.layerOps.test.ts）。
export function applyRoadMaterialTrackOffsets(
  map: MapLibreMap,
  visible: { roadSurface: boolean; roadType: boolean; designation: boolean; tunnel: boolean; oneway: boolean },
) {
  runWhenStyleReady(map, () => {
    const visibleByLayerId: Record<string, boolean> = {
      [ROAD_TILE_LAYER_ID]: visible.roadSurface,
      [ROAD_TYPE_LAYER_ID]: visible.roadType,
      [DESIGNATION_LAYER_ID]: visible.designation,
      [TUNNEL_LAYER_ID]: visible.tunnel,
      [ONEWAY_LAYER_ID]: visible.oneway,
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

// designation（指定路線）・tunnel・oneway（いずれも一次属性、路面と同じベクタソースを
// 再利用する独立レイヤー）は、レイヤーID・色/不透明度式以外まったく同一のため、
// makeEnsureAxisRampLayer/makeEnsureDedicatedWayValueLayerと同じ「1ファクトリ+N呼び出し」
// パターンで共通化する。プロパティは該当区間のみ値を持ち、未該当はプロパティ欠落として
// 各色式のcoalesce/case式が灰色（designation）・中立色（tunnel/oneway）に倒す。
// specOwnsFilter=false: このレイヤーの絞り込みは凡例のON/OFFから`setStaticOverlayFilters`が
// 組み立てて与える。ここで触ると、表示ON/OFFのたびに走る`ensure`が利用者の絞り込みを巻き戻す。
function makeEnsureAttributeLineLayer(
  layerId: string,
  colorExpression: unknown[],
  opacityExpression: unknown[],
): (map: MapLibreMap) => void {
  return (map: MapLibreMap) => {
    const applyData = () => {
      ensureLayerFromSpec(
        map,
        {
          id: layerId,
          type: "line",
          source: ROAD_TILE_SOURCE_ID,
          "source-layer": ROAD_TILE_SOURCE_LAYER,
          paint: {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            "line-color": colorExpression as any,
            "line-width": 3,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            "line-opacity": opacityExpression as any,
          },
          layout: { visibility: "none" },
        },
        { specOwnsFilter: false },
      );
    };
    runWhenStyleReady(map, applyData);
  };
}

// 事故レイヤー（外部静的データソース）。road_surfaceとは独立のベクタソース・タイル
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

// 停止要因POI・交差点密度は点データのため、路面・車ストレス・自転車
// インフラとは別のベクタソース（region-poi-tiles）を使う。ズーム範囲は路面と同じ
// （regionApi.ts: ROAD_TILE_MIN_ZOOM/MAX_ZOOM、backend側も同じ範囲に準拠）。
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

// 補給・休憩ポイントPOI。停止要因POIと同じregion-poi-tiles
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
// ものは、いずれも「初期化時にensureで一度だけ追加、以降はvisibilityの切替のみ」という
// 同型の生存期間を持つ。各レイヤーの見た目（addLayerの中身）は上のensure*Layer関数に残しつつ、
// 「どのpropsフラグがどのensure関数・layerIdに対応するか」の対応表だけをここに集約する。
// 二次軸の汎用rampレイヤー。axis-catalog.json（backendレジストリ生成物）の
// kind="ramp"軸ごとに、road_surfaceタイルへ焼き込み済みの事実プロパティ（per-km密度）を
// カタログ宣言のしきい値で色分けする線レイヤーを自動生成する。ensure関数は他の静的
// レイヤー（makeEnsureAttributeLineLayer等）と同じ「初期化時に一度だけ追加、以降は
// visibility切替のみ」パターンだが、axis（軸スタジオのしきい値・色定義）は実行時
// フェッチで後から変わりうるため、レイヤーが既に存在する場合もsetPaintPropertyで
// 再適用する。
//
// 下敷き表現（useCasing: 材料が同時表示中なら太く半透明、そうでなければ1次と同じ太さ・
// 不透明度）もこのspecの一部として持つ。`ensureLayerFromSpec`はレイヤーが既にあるとき
// specのpaintを丸ごと再適用するため、太さ・不透明度をspecの外から別途setPaintPropertyする
// 形にすると、以後どこかでensureが呼ばれた時点（絞り込みの再適用等）に無条件でspec側の値へ
// 巻き戻る。
// specOwnsFilter=false: ramp軸の凡例フィルタも`setStaticOverlayFilters`が持つ
// （`makeEnsureAttributeLineLayer`と同じ）。
function makeEnsureAxisRampLayer(axis: RampAxis, useCasing: boolean): (map: MapLibreMap) => void {
  return (map: MapLibreMap) => {
    runWhenStyleReady(map, () => {
      // 参照するソースは自分で用意する（makeEnsureDedicatedWayValueLayerと同じ）。
      // map.setStyle()の後の作り直しはレイヤーごとのensureを順に呼ぶだけで、路面ソースを
      // 作る処理がこれより後に来ることがある——順序に頼るとそのときだけレイヤーが落ち、
      // その軸の色分けが戻らない。
      ensureRoadSurfaceTileLayer(map);
      const layerId = axisLineLayerId(axis.axisId);
      const colorExpression = buildAxisRampColorExpression(axis);
      ensureLayerFromSpec(
        map,
        {
          id: layerId,
          type: "line",
          source: ROAD_TILE_SOURCE_ID,
          "source-layer": ROAD_TILE_SOURCE_LAYER,
          paint: {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            "line-color": colorExpression as any,
            "line-width": useCasing ? SECONDARY_AXIS_CASING_WIDTH : DEFAULT_ROAD_LINE_WIDTH,
            "line-opacity": useCasing ? SECONDARY_AXIS_CASING_OPACITY : KNOWN_LINE_OPACITY,
          },
          layout: { visibility: "none" },
        },
        { specOwnsFilter: false },
      );
    });
  };
}

// interactive: クリック・カーソル判定（handleClick/handleMouseMove）の対象にするか。
// レイヤーを足すときにその場で答えさせるため必須にしてある——別の一覧で「対象外のkey」を
// 数え上げる形にすると、新しいレイヤーが既定でクリック対象になり、「カーソルは
// クリック可能を示すのに実際は何も起きない」という不整合が静かに増える。
type OverlayLayerEntry = {
  key: string;
  layerId: string;
  ensure: (map: MapLibreMap) => void;
  interactive: boolean;
};

// 軸スタジオが公開したramp軸（ビルド時静的フォールバックに限らず、実行時フェッチで
// 増減しうる）を反映できるよう関数化してある。呼び出し側（コンポーネント内、useMemo経由）が
// rampAxesを渡す。テスト（MapView.overlayFilters.test.ts等）から
// build*(RAMP_AXES)として直接呼べるようexportしている。
//
// 2次（ramp軸）を太く半透明な下敷きにするのは、その材料（1次）が同時に表示されている
// ときだけにする。材料が1つも表示されていなければ下に隠すものが無いため、通常の太さ・
// 不透明度（1次と同じ、DEFAULT_ROAD_LINE_WIDTH/KNOWN_LINE_OPACITY）に戻す（常に太く
// 半透明にすると、道路網が密な都市部では下敷きの重なりだけで地図全体がぼやけて
// 見えてしまう）。casingLayerKeysは、どの2次レイヤーの材料が現在表示中かをpage.tsx側
// （axisMaterialLayerIds）が判定して渡す（このファイルはレイヤー固有の材料関係を
// 知らない汎用描画係のまま、という方針を保つ）。キーはaxisMapLayerId（"axis:car_stress"等）。
export function buildAxisOverlayLayers(
  rampAxes: readonly RampAxis[],
  casingLayerKeys: ReadonlySet<string> = new Set(),
): readonly OverlayLayerEntry[] {
  return rampAxes.map((axis) => {
    const key = axisMapLayerId(axis.axisId) as string;
    return {
      key,
      layerId: axisLineLayerId(axis.axisId),
      ensure: makeEnsureAxisRampLayer(axis, casingLayerKeys.has(key)),
      // 内訳ポップアップ（axisInspectorPopup等）に対応する専用表示を持たない。
      interactive: false,
    };
  });
}

// map.addLayer()はbeforeId省略時にレイヤースタックの最上位へ積み上げるため、この配列の
// 並び順がそのままensureAllStaticOverlayLayers（下記）でのensure()呼び出し順＝実際の
// 描画の重なり順（先＝背面、後＝前面）になる。
// ramp軸（車の圧迫感・停止密度・事故密度等、推定/composite、SECONDARY_AXIS_CASING_
// WIDTH/OPACITYの太く半透明な下敷き）をroad_surface本体の直上へまとめ、
// designation・accidents・stopPoi・supplyPoi（観測/raw、通常の太さ・不透明度のくっきりした
// 上書き）をその上に置く——観測データと推定を同時に表示したとき、後から追加される側が
// 先に追加された側を塗り潰さないようにする並び順である。
export function buildStaticOverlayLayers(
  axisOverlayLayers: readonly OverlayLayerEntry[],
  // 専用way値配信軸の一覧（軸カタログ由来）。レイヤーの登録自体をこの一覧から導出するため、
  // 軸スタジオで3件目を公開すれば地図レイヤーもそのまま増える。
  dedicatedAxes: readonly DedicatedWayValueAxis[],
  // `dedicated_way_value_layer`軸のmap_value_thresholdsを
  // 軸id→しきい値配列の汎用Mapとして受け取る（MapViewProps.dedicatedWayValueDisplays参照）。
  dedicatedWayValueDisplays?: ReadonlyMap<string, DedicatedWayValueDisplay>,
  // 同じ軸id→booleanの汎用Mapとして、フェッチ進行中かどうかを受け取る
  // （MapViewProps.dedicatedWayValueLoading参照）。
  dedicatedWayValueLoading?: ReadonlyMap<string, boolean>,
): readonly OverlayLayerEntry[] {
  return [
    // ラスタタイルのため地物クリック判定が効かない。
    { key: "elevation", layerId: GSI_RELIEF_LAYER_ID, ensure: ensureGsiReliefLayer, interactive: false },
    { key: "landcover", layerId: LANDCOVER_LAYER_ID, ensure: ensureLandcoverLayer, interactive: false },
    ...axisOverlayLayers,
    {
      key: "designation",
      layerId: DESIGNATION_LAYER_ID,
      ensure: makeEnsureAttributeLineLayer(
        DESIGNATION_LAYER_ID,
        DESIGNATION_COLOR_EXPRESSION,
        DESIGNATION_OPACITY_EXPRESSION,
      ),
      interactive: true,
    },
    {
      key: "tunnel",
      layerId: TUNNEL_LAYER_ID,
      ensure: makeEnsureAttributeLineLayer(TUNNEL_LAYER_ID, TUNNEL_COLOR_EXPRESSION, TUNNEL_OPACITY_EXPRESSION),
      interactive: true,
    },
    {
      key: "oneway",
      layerId: ONEWAY_LAYER_ID,
      ensure: makeEnsureAttributeLineLayer(ONEWAY_LAYER_ID, ONEWAY_COLOR_EXPRESSION, ONEWAY_OPACITY_EXPRESSION),
      interactive: true,
    },
    // 専用way値配信軸（評価軸グループとしての風・勾配等）。ensureは
    // makeEnsureDedicatedWayValueLayer内でensureRoadSurfaceTileLayer（promoteId付き
    // source）を先に呼ぶ。keyはmapLayers.tsのMapLayerIdと同じ値でなければならない
    // （setStaticOverlayVisibilityがvisibility辞書をこのkeyで引くため）。
    ...dedicatedAxes.map((axis) => ({
      key: dedicatedWayValueMapLayerId(axis.axisId) as string,
      layerId: dedicatedWayValueLineLayerId(axis.axisId),
      ensure: makeEnsureDedicatedWayValueLayer(
        dedicatedWayValueLineLayerId(axis.axisId),
        dedicatedWayValueColorExpression(
          axis.axisId,
          dedicatedWayValueDisplays?.get(axis.axisId),
          dedicatedWayValueLoading?.get(axis.axisId) ?? false,
        ),
      ),
      interactive: true,
    })),
    { key: "accidents", layerId: ACCIDENT_LAYER_ID, ensure: ensureAccidentTileLayer, interactive: true },
    { key: "stopPoi", layerId: STOP_POI_LAYER_ID, ensure: ensureStopPoiLayer, interactive: true },
    { key: "supplyPoi", layerId: SUPPLY_POI_LAYER_ID, ensure: ensureSupplyPoiLayer, interactive: true },
  ];
}

type StaticOverlayKey = string;

// レイヤーごとのデータ取得状態の算出元となる(source, source-layer)対応表。
// roadType/roadSurface/designation/tunnel/oneway/車の圧迫感等のramp軸は同じroad_surface
// タイルを再利用しているため（road_edgesが未構築の地点では、これらのレイヤーが同時に
// empty/errorになるのが正しい挙動）、あえて同じ
// sourceId/sourceLayerを指す。elevationは国土地理院のラスタタイルで
// source-layerを持たないため、取得失敗のみ検知しempty判定はしない。routeは自前データ
// （選択中候補のgeometryをそのままGeoJSON化するのみ）のためこの表の対象外。
// MapView.segments.test.tsと同じ考え方で、computeLayerDataStatusのテスト
// （MapView.dataStatus.test.ts）からbuildLayerDataSources(RAMP_AXES)経由で
// 個別レイヤーのsourceIdを参照できるようexportしている。
// 動的気象レイヤー（降水ナウキャスト・風・雷/竜巻・雷放電位置データ・キキクル4種）は
// この表の対象外——実際の外部フェッチが自前のJSコード（`usePolledFetch`等）で
// 行われ、結果をsetData/setTilesで流し込むだけのため、MapLibreのソースイベントは外部
// フェッチの待ち時間・失敗を観測できない。データ取得状態は`useDynamicWeatherLayers.ts`が
// 各要素のフェッチ自身のloading/errorから直接算出する（`dynamicWeatherDataStatus`）。
type LayerDataSource = { key: MapLayerId; sourceId: string; sourceLayer?: string };

// buildAxisOverlayLayers等と同じ理由で関数化してある。テスト
// （MapView.dataStatus.test.ts）からbuild*(RAMP_AXES)として直接呼べるようexportしている。
export function buildLayerDataSources(rampAxes: readonly RampAxis[]): readonly LayerDataSource[] {
  return [
    { key: "roadType", sourceId: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
    { key: "roadSurface", sourceId: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
    { key: "designation", sourceId: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
    { key: "tunnel", sourceId: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
    { key: "oneway", sourceId: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
    { key: "accidents", sourceId: ACCIDENT_TILE_SOURCE_ID, sourceLayer: ACCIDENT_TILE_SOURCE_LAYER },
    { key: "stopPoi", sourceId: POI_TILE_SOURCE_ID, sourceLayer: STOP_POI_SOURCE_LAYER },
    { key: "supplyPoi", sourceId: POI_TILE_SOURCE_ID, sourceLayer: STOP_POI_SOURCE_LAYER },
    { key: "elevation", sourceId: GSI_RELIEF_SOURCE_ID },
    { key: "landcover", sourceId: LANDCOVER_SOURCE_ID },
    // 二次軸rampレイヤー（car_stressを含む）はroad_surfaceタイルへ
    // 焼き込み済みのプロパティを読む（designation等と同じソース共有。
    // ROAD_SURFACE_SHARED_LAYER_IDSにも登録済み）
    ...rampAxes.map((axis) => ({
      key: axisMapLayerId(axis.axisId) as MapLayerId,
      sourceId: ROAD_TILE_SOURCE_ID,
      sourceLayer: ROAD_TILE_SOURCE_LAYER,
    })),
  ];
}

// レイヤーデータ状態（loading/empty/error）の算出・追跡（computeLayerDataStatus・
// clearStaleTrackedSourceErrors・状態管理）はuseLayerDataStatus.tsに集約されている。
// buildLayerDataSources自体はbuildStaticOverlayLayers等の他の関数と同じくこのファイルに
// 残し、フックへ引数として渡す（フック側からMapView.tsxを逆importしないため）。

// クリック判定・カーソル変更（handleClick/handleMouseMove）の対象レイヤー一覧。
// 各レイヤーが自分で宣言した`interactive`から導く（対象外のkeyをここで数え上げない、
// OverlayLayerEntryのコメント参照）。これへSTATIC_OVERLAY_LAYERSの対象外である
// DETAIL_HIT_LAYER_ID（ルート詳細区間の当たり判定専用レイヤー。幅6pxの見た目の線
// DETAIL_LAYER_ID自体はモバイルでタップしづらいため、幅24pxの当たり判定専用レイヤーを
// 別に持つ）・ROAD_TILE_LAYER_ID（路面）・ROAD_TYPE_LAYER_ID（道路の種類）を加える。handleClick/handleMouseMoveの両方が
// この同じ一覧を参照する必要があり、片方だけ増減すると「ポップアップは出るがカーソルが
// 変わらない」という非対称な劣化になるため、この関数へ集約する。
// exportはテスト専用（MapView.overlayFilters.test.ts）。
export function buildInteractiveLayerIds(staticOverlayLayers: readonly OverlayLayerEntry[]): string[] {
  return [
    DETAIL_HIT_LAYER_ID,
    ROAD_TILE_LAYER_ID,
    ROAD_TYPE_LAYER_ID,
    ...staticOverlayLayers.filter((layer) => layer.interactive).map((layer) => layer.layerId),
  ];
}

function ensureAllStaticOverlayLayers(map: MapLibreMap, staticOverlayLayers: readonly OverlayLayerEntry[]) {
  for (const layer of staticOverlayLayers) layer.ensure(map);
}

function setStaticOverlayVisibility(
  map: MapLibreMap,
  flags: Record<StaticOverlayKey, boolean>,
  staticOverlayLayers: readonly OverlayLayerEntry[],
) {
  runWhenStyleReady(map, () => {
    for (const layer of staticOverlayLayers) {
      layer.ensure(map);
      setLayerVisibility(map, layer.layerId, flags[layer.key]);
    }
  });
}

// 標高を除く各レイヤー（指定路線・事故・停止要因POI等）の絞り込み。
// STATIC_FILTER_AXES（staticAttributeLayers.ts）のlayerIdでSTATIC_OVERLAY_LAYERSのkeyと
// 突き合わせ、そのレイヤーが持つ軸ぶんを道路情報と同じ
// buildCombinedLegendFilterExpressionでAND束ねする。軸を持たない標高はスキップする（setFilterはvector/circleレイヤー用で
// ラスタレイヤーには使えないため）。
//
// car_stressはbackendのtile_inputs/thresholds（registry_defaults.py）から静的に決まる
// ramp軸のため、他のramp軸（surface_q/accident等）と同じ扱いで統一的に処理できる。
// MapView.overlayFilters.test.tsからフェイクmapで検証できるようexportしている
// （computeLayerDataStatus等と同じ方針）。
export function setStaticOverlayFilters(
  map: MapLibreMap,
  hiddenKeysByAxis: Record<StaticFilterAxisId, readonly string[]>,
  staticOverlayLayers: readonly OverlayLayerEntry[],
  staticFilterAxes: readonly StaticFilterAxis[],
) {
  runWhenStyleReady(map, () => {
    for (const layer of staticOverlayLayers) {
      const axes = staticFilterAxes.filter((axis) => axis.layerId === layer.key);
      if (axes.length === 0) continue;
      layer.ensure(map);
      const filter = buildCombinedLegendFilterExpression(
        axes.map((axis) => ({
          legend: axis.legend,
          hiddenKeys: hiddenKeysByAxis[axis.axisId] ?? [],
          baseFilter: axis.baseFilter,
        })),
      );
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map.setFilter(layer.layerId, filter as any);
    }
  });
}

// road_surfaceタイルを共有するレイヤー（mapLayers.ts: buildRoadSurfaceSharedLayerIds、
// 軸スタジオの公開ramp軸を含む）のいずれかが表示ONかを判定する。road_surfaceソースを
// 参照する箇所（ズーム範囲外判定・レイヤーデータ状態表示の抑制）が両方ともこのヘルパー
// 経由でroadSurfaceSharedLayerIdsを参照するようにし、「対象レイヤーはどれか」を1箇所
// （mapLayers.ts）だけが知っていればよい状態にする。road自体がOFFでもcarStress等の
// ramp軸だけがONであればズーム範囲外の案内対象に含める必要があるため、road単体の表示
// 状態ではなくこの判定を使う。MapView.segments.test.tsと同じ考え方でテスト可能に
// exportしている。
//
// roadSurfaceSharedLayerIdsは第2引数として実行時に渡す——ビルド時静的フォールバック
// ROAD_SURFACE_SHARED_LAYER_IDSを直接参照すると、軸スタジオで新規公開したramp軸を
// 低ズームでONにしても「表示範囲が広すぎます」の案内が出ないまま何も表示されない状態に
// なるため、呼び出し元がpropsのrampAxesから実行時に算出したリストを渡す。
//
// 第1引数は表示状態のRecordではなく**propsの形そのもの**を受け取り、レイヤーidキーへの
// 合流をこの関数の中で行う。静的レイヤーは個別のbooleanで、軸レイヤーはレイヤーidキーの
// Recordで来るため、呼び出し側で組み立てる形にすると軸のRecordを合流し忘れても型が通り、
// 第2引数が挙げる軸レイヤーidが常にundefined＝案内が一度も出ない状態になる。
export interface RoadSurfaceGroupState {
  showRoadType: boolean;
  showRoadSurface: boolean;
  showDesignation: boolean;
  showTunnel: boolean;
  showOneway: boolean;
  /** ramp軸レイヤーの表示状態。キーは`axisMapLayerId`（"axis:car_stress"等）。 */
  axisVisibility: Readonly<Record<string, boolean>>;
  /** 専用way値配信軸レイヤーの表示状態。キーは`dedicatedWayValueMapLayerId`。 */
  dedicatedWayValueVisibility: Readonly<Record<string, boolean>>;
}

export function isRoadSurfaceGroupVisible(
  state: RoadSurfaceGroupState,
  roadSurfaceSharedLayerIds: readonly MapLayerId[],
): boolean {
  const visibility: Record<string, boolean> = {
    roadType: state.showRoadType,
    roadSurface: state.showRoadSurface,
    designation: state.showDesignation,
    tunnel: state.showTunnel,
    oneway: state.showOneway,
    ...state.dedicatedWayValueVisibility,
    ...state.axisVisibility,
  };
  return roadSurfaceSharedLayerIds.some((id) => visibility[id]);
}

// 路面はvector sourceのminzoomにより、そのズームレベル未満ではタイルが要求・描画されない。
// 「表示範囲が広すぎます」の案内は、この閾値を現在のズームと比較して判定する
// （標高はラスタタイルのためこの判定の対象外）。
// showRoadSurfaceGroupは isRoadSurfaceGroupVisible の結果（road_surfaceタイルを共有する
// 各レイヤーのいずれかが表示ONか）——road自体がOFFでもcarStress等の他レイヤーが同じ
// ソースを見ていればこの案内の対象に含める。
function updateRoadZoomHint(map: MapLibreMap, showRoadSurfaceGroup: boolean, onChange: (tooWide: boolean) => void) {
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

// ルート全体を収めるときの基本余白（全辺）。地図の縁に候補線が貼り付かない程度の値。
const ROUTE_FIT_BASE_PADDING_PX = 40;
// フィット後に必ず残す可視領域の幅・高さ。覆っているUIが大きいとき（モバイルで
// ボトムシートを上限まで伸ばした場合等）に、padding同士が地図の縦・横を食い尽くして
// MapLibreが破綻したズームを算出するのを防ぐ。
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
export function computeRouteFitPadding(
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

// ポップアップ本文の共通スタイル。line-height 1.4はサイドバーの他カード
// （components/ui/Card等）に近い密度に合わせている。
const POPUP_BODY_STYLE = "font-size:var(--font-size-md); line-height:1.4;";

// 区間クリックの当たり判定（DETAIL_HIT_LAYER_ID、幅24px）は見た目の線（6px）より広いため、
// クリック地点（e.lngLat）をそのままマーカー位置に使うと、ルート線から目に見えてズレた
// 場所にマーカーが立ってしまう。クリックされた区間のgeometry（LineString）上で
// クリック地点にもっとも近い点を求め、そちらをマーカー位置として使う
// （handleRouteSegmentClick参照）。区間規模の距離感での見た目上のスナップが目的のため、
// 球面上の正確な最近点ではなく経緯度を平面とみなした単純な線分への垂線ベースの近似で十分
// （道路レベルのローカルな距離では誤差は無視できる）。
export function nearestPointOnLineString(
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

// ルート線クリック時、区間クリックは軽量なマーカーのみを地図上に立て、地点・到達予想
// 時刻・軸別の内訳（積み上げバー、AxisContributionBar）はすべてボトムシート側
// （page.tsx: selectedRouteSegment state、RouteAxisProfile）が表示する
// （handleRouteSegmentClick参照）。地図上にフローティングポップアップでレーダーチャートを
// 出す方式は、モバイルで「ルート結果」ボトムシートに隠れる・軸数が少ないとレーダーが
// 機能しない問題があるため採らない。

// 静的道路属性P0（docs/static-road-attributes-plan.md）で追加したプロパティ。
// タグ・算出不能はundefined/null（MVTのST_AsMVTがNULLプロパティを省略するため、
// 実際にはキー自体が存在しない）。
export type { RoadSurfacePopupProperties } from "./roadFacts";

// 外部静的データソース（警察庁交通事故統計）のクリックポップアップ用プロパティ。
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

// 停止要因POI・補給休憩POIのクリックポップアップ用プロパティは同じ形（{kind}）で、
// ラベル辞書とprefix文言が違うだけのため、1つの関数へ統合する。
interface PoiPopupProperties {
  kind?: string | null;
}

function buildPoiPopupHtml(prefix: string, labels: Record<string, string>, properties: PoiPopupProperties): string {
  const label = properties.kind ? labelOrEscapedRaw(labels, properties.kind) : "不明";
  return `<div style="${POPUP_BODY_STYLE}">${prefix}: ${label}</div>`;
}

interface MapViewProps {
  routes: RouteCandidate[];
  selectedRouteId: string | null;
  // 比較相手が別の道を通る区間（docs/tasks/T621.md）。空/未指定なら帯を出さない。
  spliceStretches?: SpliceStretchFeature[];
  /** 編集中に「いま作っているルート」として描く座標列（編集していなければ省略）。 */
  splicedRoute?: readonly GeoJSON.Position[] | null;
  /** 乗り換えられる区間の帯をタップしたときに呼ばれる（`SpliceStretchFeature.index`）。
   * 選ぶ操作の中心を地図へ置くためのもの——パネルの行だけで選ばせると、どの行がどの帯かを
   * 目で対応づける必要がある。 */
  onSpliceStretchSelect?: (index: number) => void;
  location: Coordinates;
  /** 出発地点マーカーの色分けに使う。GPS取得失敗時のフォールバック（"default"）だけを
   * グレーで視覚的に区別する。実際のGPS取得（"geolocation"）と手動指定（"manual"）は
   * どちらも「意図した位置」という点で同格のため、赤で区別しない。 */
  locationSource: LocationSource;
  showElevation: boolean;
  showLandcover: boolean;
  /** 動的気象レイヤー。要素id（DynamicWeatherLayerId）ごとに、ソースキー→ON/OFFと
   * page.tsx側が各要素のデータ層関数（precipitationRenderPayload/windRenderPayload）から
   * 計算した「選択中の共有時刻に対応するペイロード」を渡す。payloadが未定（フェッチ未完了・
   * 取得失敗、あるいは選択時刻がその要素のデータ範囲外で「描画しない」場合）の間はvisible=
   * trueでも非表示のまま（DYNAMIC_WEATHER_RENDERERS・applyDynamicWeatherState参照）。
   * 要素・ソースを追加してもこのプロパティ自体は変わらない。 */
  dynamicWeather: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>>;
  /** 道路の種類。太さ・線種で反映する。物理描画はshowRoadSurfaceと同じMapLibre線レイヤーへ
   * 合成される（MapView.tsx: applyRoadLayerState参照）。 */
  showRoadType: boolean;
  /** 路面の種類。色で反映する。 */
  showRoadSurface: boolean;
  /** 指定路線（外部静的データソース、KSJ N10/N12）。路面と同じソースを再利用する独立レイヤー。
   * 自転車インフラは専用の地図レイヤーを持たず、評価軸bicycle_infra_qualityとして表現する。 */
  showDesignation: boolean;
  /** トンネル（一次属性、OSMのtunnelタグ）。designationと同じく路面と同じソースを
   * 再利用する独立レイヤー。 */
  showTunnel: boolean;
  /** 一方通行（一次属性、OSM onewayタグ）。tunnelと同じく路面と同じソースを
   * 再利用する独立レイヤー。評価軸には組み込まない表示専用。 */
  showOneway: boolean;
  /** 専用way値配信軸（「評価軸」グループの風・勾配等）の表示フラグを、
   * レイヤーID（`${axisId}Axis`、mapLayers.ts: MapLayerId）→booleanの汎用Recordとして
   * 受け取る（axisVisibilityと同じ形）。designation/tunnel/onewayと同じく路面と同じ
   * ソースを再利用する独立レイヤーだが、値はタイルのプロパティではなくdedicatedWayValues
   * （別経路のAPI、setFeatureStateで合成）から来る。軸ごとに別名のpropを新設しない
   * （design-principles.md構造仕様3）。 */
  dedicatedWayValueVisibility: Record<string, boolean>;
  /** 専用way値配信軸の一覧（軸カタログ由来）。レイヤー登録・ズーム範囲外判定の対象を
   * この一覧から導出する（rampAxesと同じ位置付け）。 */
  dedicatedAxes: readonly DedicatedWayValueAxis[];
  /** hooks/useDedicatedWayValues.tsが現在のビューポートに対して取得したway_id→値
   * （風=wind_drag_ratio[m/s、正=向かい風・負=追い風]、勾配=effective_gradient[%、
   * 正=登り・負=下り]）を、axisId→(way_id→値)の汎用Mapとしてまとめて受け取る
   * （page.tsx: useDedicatedWayValuesの結果を軸id→valuesへ写して構築）。
   * show{Wind,Gradient}Axisがtrueの間、変化のたびにMapLibreのsetFeatureStateで
   * 路面タイルの地物へ差し込む（applyAxisFeatureStateValues参照）。軸ごとに別名のpropを
   * 新設せず（design-principles.md構造仕様3参照）汎用Mapへ統合してある。未設定の軸idは
   * 空Map扱い（get()がundefinedを返す）として処理される。 */
  dedicatedWayValues: ReadonlyMap<string, ReadonlyMap<number, number>>;
  /** `dedicated_way_value_layer`軸の地図表示宣言（種類・単位・しきい値・段階ラベル、
   * 軸カタログ由来）をaxisId→宣言の汎用Mapとして受け取る（page.tsx: axisCatalog.axesから
   * `dedicatedWayValueLayer===true`の軸を横断的に抽出して構築）。評価軸グループの線・
   * 環境グループの勾配gridFillがこの1つのMapから該当軸の宣言を引く。未設定の軸idは
   * 難易度スケールの既定（dedicatedWayValueLayer.ts: DEFAULT_DEDICATED_WAY_VALUE_DISPLAY）
   * へフォールバックする。 */
  dedicatedWayValueDisplays?: ReadonlyMap<string, DedicatedWayValueDisplay>;
  /** `dedicated_way_value_layer`軸ごとのフェッチ進行中フラグ
   * （hooks/useDedicatedWayValues.ts: loading）をaxisId→booleanの汎用Mapとして受け取る。
   * dedicatedWayValueDisplaysと同じ理由（design-principles.md構造仕様3: 軸ごとにpropを
   * 新設しない）で、windLoading/gradientLoadingのような別名propは持たない。未設定の軸idは
   * false（フェッチ中でない）扱い。 */
  dedicatedWayValueLoading?: ReadonlyMap<string, boolean>;
  /** 事故（外部静的データソース、警察庁交通事故統計）。road_surfaceとは独立のソース。 */
  showAccidents: boolean;
  /** 停止要因POI。路面とは別の点データ用ベクタソースを使う。 */
  showStopPoi: boolean;
  /** 補給・休憩ポイントPOI（コンビニ・自販機・トイレ・給水・駐輪場）。
   * 停止要因POIと同じベクタソース（region-poi-tiles）を共有する独立レイヤー。 */
  showSupplyPoi: boolean;
  /** 二次軸rampレイヤーの表示フラグ。キーはaxisMapLayerId（"axis:accident"等、
   * mapLayers.tsのMapLayerIdと同じ）。カタログ駆動のため個別のshow*フラグは持たない。 */
  axisVisibility: Record<string, boolean>;
  /** 2次（ramp軸、車の圧迫感を含む）のうち、材料（1次）が同時に表示されているためcasing
   * （太く半透明な下敷き）で描くべきレイヤーのkey集合（"axis:car_stress"/"axis:accident"等、
   * STATIC_OVERLAY_LAYERSのkeyと同じ）。page.tsx側がaxisMaterialLayerIdsとlayerVisibility
   * から算出する（buildAxisOverlayLayers参照）。 */
  secondaryAxisCasingLayerIds: readonly string[];
  /** 路面の各軸（路面の種類・道路の種類）それぞれの非表示カテゴリキー。軸ごとに独立した
   * レイヤーを持つため、絞り込みもレイヤーごとに独立して効く。 */
  roadHiddenKeysByMode: Record<RoadFilterAxisId, readonly string[]>;
  /** 自転車インフラ・指定路線・停止要因POI・事故（当事者/重大度）の絞り込み軸
   * （STATIC_FILTER_AXES参照。事故のみ2軸を持ち、他は1軸。車の圧迫感は
   * axisVisibility側と同様RAMP_AXES由来のためここには手書きされていない）。 */
  staticLegendHiddenKeysByAxis: Record<StaticFilterAxisId, readonly string[]>;
  routeLayerOn: boolean;
  /** ルート色分けモード一覧（axis-catalog由来、公開軸を無条件で動的に含む）。
   * page.tsx: axisCatalog.routeStyleModes（フェッチ完了までは静的フォールバック）を
   * そのまま渡す。 */
  routeStyleModes: readonly RouteStyleMode[];
  routeStyleModeId: RouteStyleModeId;
  hiddenRouteLegendKeys: readonly string[];
  onRegionZoomHintChange: (tooWide: boolean) => void;
  /** パン・ズーム確定（moveend/zoomend）のたびに現在のビューポート（bbox・
   * ズーム）を呼び出し側へ伝える。風の詳細格子（ヒートマップ用）のように「今見えている
   * 範囲だけ」を対象にフェッチしたいレイヤーが、page.tsx側でデバウンス・ズーム閾値判定
   * したうえで使う想定。onRegionZoomHintChangeと違い道路タイル固有の判定を持たない、
   * 汎用のビューポート通知（今後同種の「見えている範囲だけ取得」レイヤーが増えたら
   * 相乗りできる）。 */
  onViewportChange: (viewport: { west: number; south: number; east: number; north: number; zoom: number }) => void;
  /** レイヤーごとのデータ取得状態（loading/empty/error）。表示ONのレイヤーが
   * 変わるたび・タイル取得の進行に応じて呼ばれる（値が変わらない限り呼ばない）。 */
  onLayerDataStatusChange: (status: LayerDataStatusByLayer) => void;
  refreshToken: number;
  /** 実験スロット（研究インターフェース改善 §10-3）。デバッグモードOFF時は呼び出し側が
   * 空配列を渡すため、通常利用ではレイヤーは作られない。 */
  experimentSlots: ExperimentSlot[];
  /** 二次軸の汎用rampレイヤー一覧。呼び出し側（page.tsx）が
   * useAxisCatalog経由で取得したもの（取得完了までとエラー時は静的フォールバック
   * RAMP_AXES）を渡す。軸スタジオでの新規公開軸もここへ含まれれば、再デプロイなしに
   * 地図レイヤーとして現れる。 */
  rampAxes: readonly RampAxis[];
  /** 公開軸すべて（順序・ラベル・説明の正本）。道をクリックしたときの詳細
   * （RoadInspectorPopup）が、ルート結果と同じ並び・同じ部品で軸ごとの効き方を出すために
   * 使う。呼び出し側（page.tsx）がuseAxisCatalog経由で取得したものを渡す。 */
  axes: readonly PreferenceAxisDef[];
  /** 軸id→色（ルート結果の寄与度バー・凡例チップと同じ配色）。 */
  axisColors: Record<string, string>;
  /** 区間クリックで選択中の区間（controlled、page.tsx側のstate）。
   * nullの間はクリック地点マーカーを表示しない。地点・到達予想時刻・軸別内訳の表示は
   * すべてボトムシート側（RouteAxisProfile）が担う——このコンポーネントはクリック地点へ
   * マーカーを立てる・onRouteSegmentSelectで選択を通知するだけで、テキストポップアップは
   * 一切出さない。 */
  selectedRouteSegment: SelectedRouteSegment | null;
  /** ルート線クリック（handleRouteSegmentClick）で呼ばれる。呼び出し元（page.tsx）が
   * selectedRouteSegment stateへ格納し、上記propとして折り返される
   * （destination/waypointsと同じcontrolled propパターン）。 */
  onRouteSegmentSelect: (selection: SelectedRouteSegment | null) => void;
  /** 地図上の候補線を押したときの候補切り替え。一覧（ルート結果の縦タブ）と地図の
   * どちらからでも選べるようにする。 */
  onRouteSelect: (routeId: string) => void;
  /** ユーザーが地図クリックで指定した経由地（起点→経由地1→...→起点の順で
   * 通過する単一経路の生成に使う、page.tsx側のstate）。 */
  waypoints: Coordinates[];
  /** 空白地点クリック時の「経由地に追加」ボタン押下で呼ばれる。 */
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
  /** 目的地（最大1点、指定時は起点に戻らず目的地で終わる片道ルートになる）。 */
  destination: Coordinates | null;
  /** 目的地マーカークリックで呼ばれる（解除）。 */
  onDestinationClear: () => void;
  /** 出発地点マーカーをドラッグ&ドロップで動かした（dragend）
   * ときに呼ばれる（page.tsx: useLocation().setManualLocation）。地図アプリで一般的な
   * 「ピンをつかんで動かす」操作そのものなので説明用のUIを別途持たない。 */
  onOriginSet: (coordinates: Coordinates) => void;
  /** 地図キャンバスの上に重なるUI（モバイルの下部タブバー・ボトムシート）で覆われている
   * 辺ごとの高さ(px)。ルート生成直後のフィットで、覆われた領域の中へルートが収まって
   * しまうのを防ぐ。MapViewはシート・タブバーの存在を知らないため、レイアウトを持つ
   * 呼び出し側（page.tsx）が算出して渡す。 */
  routeFitObscuredPx?: RouteFitObscuredPx;
}

/** 中身（キーと値）が変わらない間は、前回と同じMapを返す。
 *
 * 呼び出し側が毎フェッチ作り直すMapを、参照の同一性に依存するuseMemo/useEffectへ
 * そのまま渡せるようにするためのもの。 */
export function useStableMap<K, V>(map: ReadonlyMap<K, V> | undefined): ReadonlyMap<K, V> | undefined {
  const signature = map
    ? [...map]
        .map(([key, value]) => `${String(key)}=${String(value)}`)
        .sort()
        .join("|")
    : "";
  // 参照ではなく中身で作り直しを決める。mapを依存へ入れると毎回作り直しになり意味が無い。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => map, [signature]);
}

/** 乗り換えられる区間の帯と、編集中の合成ルートの出し分けを1箇所へ集約する。
 *
 * 「ルート」チップOFFのときは帯も合成ルートも出さない——候補線が消えている地図に
 * 差し替え先だけが浮いて見えるのを避けるため。 */
export function applySpliceLayerVisibility(
  map: MapLibreMap,
  routeLayerOn: boolean,
  spliceStretches: SpliceStretchFeature[] | undefined,
  splicedRoute: readonly GeoJSON.Position[] | null | undefined,
) {
  const stretches = routeLayerOn ? (spliceStretches ?? []) : [];
  if (stretches.length > 0) {
    drawSpliceStretches(map, stretches);
  } else {
    hideSpliceStretches(map);
  }
  const current = routeLayerOn ? (splicedRoute ?? null) : null;
  if (current && current.length > 1) {
    drawSplicedRoute(map, current);
  } else {
    hideSplicedRoute(map);
  }
}

/** `redrawAllLayers`が読む表示状態。コンポーネント側はrefで最新値を保持して渡す。 */
export type RedrawAllLayersProps = Pick<
  MapViewProps,
  | "routes"
  | "selectedRouteId"
  | "routeLayerOn"
  | "routeStyleModes"
  | "routeStyleModeId"
  | "hiddenRouteLegendKeys"
  | "spliceStretches"
  | "splicedRoute"
  | "showElevation"
  | "showLandcover"
  | "dynamicWeather"
  | "showRoadType"
  | "showRoadSurface"
  | "showDesignation"
  | "showTunnel"
  | "showOneway"
  | "dedicatedWayValueVisibility"
  | "showAccidents"
  | "showStopPoi"
  | "showSupplyPoi"
  | "axisVisibility"
  | "roadHiddenKeysByMode"
  | "staticLegendHiddenKeysByAxis"
  | "experimentSlots"
  | "dedicatedWayValues"
  | "onRegionZoomHintChange"
> & {
  staticOverlayLayers: readonly OverlayLayerEntry[];
  staticFilterAxes: readonly StaticFilterAxis[];
  roadSurfaceSharedLayerIds: readonly MapLayerId[];
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
// 置き忘れは`scripts/review_checks.py`の`map_redraw_coverage`が機械的に落とす。
//
// カメラは動かさない——再描画は見た目を作り直すだけで、表示範囲は利用者の操作に属する
// （フィットは「候補一覧が変わったとき」だけ、という下部effectの取り決めを破らない）。
export function redrawAllLayers(map: MapLibreMap, props: RedrawAllLayersProps) {
  const {
    routes,
    selectedRouteId,
    routeLayerOn,
    routeStyleModes,
    routeStyleModeId,
    hiddenRouteLegendKeys,
    spliceStretches,
    splicedRoute,
    showElevation,
    showLandcover,
    dynamicWeather,
    showRoadType,
    showRoadSurface,
    showDesignation,
    showTunnel,
    showOneway,
    dedicatedWayValueVisibility,
    showAccidents,
    showStopPoi,
    showSupplyPoi,
    axisVisibility,
    roadHiddenKeysByMode,
    staticLegendHiddenKeysByAxis,
    experimentSlots,
    staticOverlayLayers,
    staticFilterAxes,
    roadSurfaceSharedLayerIds,
    dedicatedWayValues,
    inspectedWayId,
    onRegionZoomHintChange,
  } = props;
  setStaticOverlayVisibility(
    map,
    {
      elevation: showElevation,
      landcover: showLandcover,
      designation: showDesignation,
      tunnel: showTunnel,
      oneway: showOneway,
      ...dedicatedWayValueVisibility,
      accidents: showAccidents,
      stopPoi: showStopPoi,
      supplyPoi: showSupplyPoi,
      ...axisVisibility,
    },
    staticOverlayLayers,
  );
  for (const id of DYNAMIC_WEATHER_LAYER_IDS) {
    applyDynamicWeatherState(map, id, DYNAMIC_WEATHER_RENDERERS[id], dynamicWeather[id]);
  }
  // 専用way値配信軸の線レイヤー（評価軸グループの風・勾配等）はプロパティ
  // ではなくsetFeatureStateで色付けするため、map.setStyle()でレイヤー自体が作り直された
  // 後は明示的に再適用しないと無色のまま残ってしまう（値自体は変わっていないため、
  // 通常の依存effectは再実行されない）。
  for (const [axisId, values] of dedicatedWayValues) {
    applyAxisFeatureStateValues(map, dedicatedWayValueFeatureStateKey(axisId), values);
  }
  setStaticOverlayFilters(map, staticLegendHiddenKeysByAxis, staticOverlayLayers, staticFilterAxes);
  applyRoadLayerState(map, showRoadSurface, showRoadType, roadHiddenKeysByMode);
  applyRoadMaterialTrackOffsets(map, {
    roadSurface: showRoadSurface,
    roadType: showRoadType,
    designation: showDesignation,
    tunnel: showTunnel,
    oneway: showOneway,
  });
  updateRoadZoomHint(
    map,
    isRoadSurfaceGroupVisible(
      {
        showRoadType,
        showRoadSurface,
        showDesignation,
        showTunnel,
        showOneway,
        axisVisibility,
        dedicatedWayValueVisibility,
      },
      roadSurfaceSharedLayerIds,
    ),
    onRegionZoomHintChange,
  );

  // applyRouteLayerVisibilityがrouteLayerOnを見て出し分けるため、「ルート」チップを
  // OFFにして候補線・ハロー・矢印を隠している間は、地図データの再読み込み
  // （map.setStyle()経由でこのredrawAllLayersが走る）でも再表示されない。
  // 直後のdetail-segments分岐（routeLayerOn && selected?.segments）と同じ基準へ揃える。
  const selected = routes.find((r) => r.id === selectedRouteId) ?? null;
  applyRouteLayerVisibility(map, routeLayerOn, routes, selectedRouteId, Boolean(selected?.segments));
  applySpliceLayerVisibility(map, routeLayerOn, spliceStretches, splicedRoute);
  drawExperimentSlots(map, experimentSlots);

  if (routeLayerOn && selected?.segments) {
    drawDetailSegments(
      map,
      selected.segments,
      getRouteStyleMode(routeStyleModes, routeStyleModeId),
      hiddenRouteLegendKeys,
    );
  } else {
    hideDetailSegments(map);
  }

  // 強調はレイヤーのfilterとvisibilityで持つため、setStyle()でソースごと消えると初期値
  // （非表示・osm_way_id=-1）に戻る。ポップアップは開いたままなので、ここで復元しないと
  // 「どの線の話か」だけが失われる。
  applyInspectedWay(map, inspectedWayId);
}

export default function MapView({
  routes,
  selectedRouteId,
  spliceStretches,
  splicedRoute,
  onSpliceStretchSelect,
  location,
  locationSource,
  showElevation,
  showLandcover,
  dynamicWeather,
  showRoadType,
  showRoadSurface,
  showDesignation,
  showTunnel,
  showOneway,
  dedicatedWayValueVisibility,
  dedicatedAxes,
  dedicatedWayValues,
  dedicatedWayValueDisplays,
  dedicatedWayValueLoading,
  showAccidents,
  showStopPoi,
  showSupplyPoi,
  axisVisibility,
  secondaryAxisCasingLayerIds,
  roadHiddenKeysByMode,
  staticLegendHiddenKeysByAxis,
  routeLayerOn,
  routeStyleModes,
  routeStyleModeId,
  hiddenRouteLegendKeys,
  onRegionZoomHintChange,
  onViewportChange,
  onLayerDataStatusChange,
  refreshToken,
  experimentSlots,
  rampAxes,
  axes,
  axisColors,
  selectedRouteSegment,
  onRouteSegmentSelect,
  onRouteSelect,
  waypoints,
  armedPinRole,
  pointEditingEnabled,
  onPinPlace,
  onWaypointRemove,
  onWaypointMove,
  destination,
  onDestinationClear,
  onOriginSet,
  routeFitObscuredPx,
}: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  // 現在マーカーへ適用済みのlocationSource（色を変える必要があるかの判定用、
  // 単なる位置更新（setLngLat）では色を変えられないmaplibregl.Markerの制約を踏まえ、
  // sourceが変わった場合だけ作り直す）。
  const appliedMarkerSourceRef = useRef<LocationSource | null>(null);
  const waypointMarkersRef = useRef<Marker[]>([]);
  const destinationMarkerRef = useRef<Marker | null>(null);
  // 区間クリックのマーカー（destinationMarkerRefと同じcontrolled prop駆動
  // パターン、下部のuseEffect参照）。
  const selectedSegmentMarkerRef = useRef<Marker | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  // 道路クリックの詳細はReactで描く（RoadInspectorPopup）。MapLibreのPopupへportalで
  // 差し込むため、開いている対象と差し込み先のDOMノードを状態として持つ。
  const [roadPopup, setRoadPopup] = useState<{
    lngLat: [number, number];
    properties: RoadSurfacePopupProperties;
  } | null>(null);
  const [roadPopupContainer, setRoadPopupContainer] = useState<HTMLDivElement | null>(null);
  // 軸スタジオが公開したramp軸を反映する派生値。propsのrampAxesが変わる
  // （useAxisCatalogの実行時フェッチが完了する）たびに再計算する。下敷き表現の有無
  // （secondaryAxisCasingLayerIds）もレイヤーspecの一部のため、材料の表示が切り替わった
  // ときもここから作り直す。
  const secondaryAxisCasingKeys = useMemo(() => new Set(secondaryAxisCasingLayerIds), [secondaryAxisCasingLayerIds]);
  const axisOverlayLayers = useMemo(
    () => buildAxisOverlayLayers(rampAxes, secondaryAxisCasingKeys),
    [rampAxes, secondaryAxisCasingKeys],
  );
  // フェッチ状態のMapは、値が同じでもフェッチのたびに作り直されて渡ってくる。そのまま
  // 依存に置くと、パン・ズームのたびに全オーバーレイ層のspecを組み直してpaint/filterを
  // 再適用することになる（公開ramp軸が増えるほど線形に増える）。中身が同じ間は同じ参照を使う。
  const stableDedicatedWayValueLoading = useStableMap(dedicatedWayValueLoading);
  const staticOverlayLayers = useMemo(
    () =>
      buildStaticOverlayLayers(
        axisOverlayLayers,
        dedicatedAxes,
        dedicatedWayValueDisplays,
        stableDedicatedWayValueLoading,
      ),
    [axisOverlayLayers, dedicatedAxes, dedicatedWayValueDisplays, stableDedicatedWayValueLoading],
  );
  const interactiveLayerIds = useMemo(() => buildInteractiveLayerIds(staticOverlayLayers), [staticOverlayLayers]);
  const layerDataSources = useMemo(() => buildLayerDataSources(rampAxes), [rampAxes]);
  const staticFilterAxes = useMemo(() => buildStaticFilterAxes(rampAxes), [rampAxes]);
  // isRoadSurfaceGroupVisibleへ渡すroadSurfaceSharedLayerIdsは、軸スタジオで新規公開した
  // ramp軸（road_surfaceタイルを共有する軸）が実行時フェッチに含まれても対象になるよう、
  // propsのrampAxesから毎回算出する。
  const roadSurfaceSharedLayerIds = useMemo(
    () => buildRoadSurfaceSharedLayerIds(rampAxes, dedicatedAxes),
    [rampAxes, dedicatedAxes],
  );
  // handleClick/handleMouseMove（地図初期化effect内、一度だけ登録されるクロージャ）が
  // 最新のinteractiveLayerIdsを読めるようにするref（onRegionZoomHintChangeRef等と同じ
  // 「安定コールバックが最新値を読む」パターン）。
  const interactiveLayerIdsRef = useRef(interactiveLayerIds);
  useEffect(() => {
    interactiveLayerIdsRef.current = interactiveLayerIds;
  }, [interactiveLayerIds]);
  // 描画コールバックはmap.once("load", ...)頼み(runWhenStyleReady)だが、スタイルURL自体が
  // 404/5xx等で取得できない場合MapLibreは"load"ではなく"error"を発火するため、地図が
  // 無言で空白のまま永久に止まる問題があった。スタイルが一度もreadyにならないまま
  // errorが起きた場合はユーザーへ可視のメッセージを出す。
  const [styleLoadFailed, setStyleLoadFailed] = useState(false);
  // 「変わらないデータを更新」によるmap.setStyle()呼び出し中（新スタイルの
  // "style.load"がまだ来ていない間）はtrue。__rcStyleReadyは一度trueになったら永久に
  // trueのまま（runWhenStyleReadyが頼る"load"は地図の生涯で一度しか発火しないため
  // リセットできない）ため、handleMapErrorのisFatal判定はこのrefも別途参照する
  // （そうしないと初回ロード成功後にsetStyle()が失敗してもstyleLoadFailedバナーが
  // 出ない）。
  const styleReloadPendingRef = useRef(false);
  // 初期表示直後は基礎地図タイルの取得が終わるまで数秒間ほぼ白紙のまま何も見えず、
  // 初めて開いたユーザーには「壊れている」ように映りかねなかった。最初のidle
  // （表示中のタイル取得が一通り落ち着いたタイミング）までスケルトンを重ねて示す。
  const [initialTilesLoading, setInitialTilesLoading] = useState(true);
  const onRegionZoomHintChangeRef = useRef(onRegionZoomHintChange);
  // 詳細を見ている道。propsではなくこのコンポーネントのstate由来のため、redrawPropsRefとは
  // 別に持つ。
  const inspectedWayIdRef = useRef<number | null>(null);
  const onViewportChangeRef = useRef(onViewportChange);
  const onLayerDataStatusChangeRef = useRef(onLayerDataStatusChange);
  // handleClick（地図初期化effect内、一度だけ登録されるクロージャ）が
  // 最新のonPinPlace・武装中の役割を読めるようにするref（onRegionZoomHintChangeRefと同じパターン）。
  const onPinPlaceRef = useRef(onPinPlace);
  const armedPinRoleRef = useRef(armedPinRole);
  const pointEditingEnabledRef = useRef(pointEditingEnabled);
  const onWaypointRemoveRef = useRef(onWaypointRemove);
  const onWaypointMoveRef = useRef(onWaypointMove);
  // 同じ理由で目的地関連のコールバック・armed状態もrefで最新値を読む。
  const onDestinationClearRef = useRef(onDestinationClear);
  // 周回モード中は空白地点クリックでの経由地追加を行わない。
  // 出発地点マーカーのdragendコールバックもrefで最新値を読む。
  const onOriginSetRef = useRef(onOriginSet);
  // フィットは「候補一覧が変わったとき」だけに限る（下部のuseEffect参照）ため、覆われて
  // いる高さの変化（シートの開閉・高さドラッグ）でフィットをやり直さないようrefで読む。
  const routeFitObscuredPxRef = useRef(routeFitObscuredPx);
  // handleRouteSegmentClick（地図初期化effect内で一度だけ登録）が最新の
  // onRouteSegmentSelectを読めるようにするref（onWaypointAddRefと同じパターン）。
  const onRouteSegmentSelectRef = useRef(onRouteSegmentSelect);
  const onRouteSelectRef = useRef(onRouteSelect);
  const onSpliceStretchSelectRef = useRef(onSpliceStretchSelect);
  // trueの間、位置更新effect（下部）がmap.flyTo（カメラ移動）をスキップする。
  // ドラッグ操作自体で既にその地点が画面内に見えているため、setManualLocation経由で
  // location/locationSourceが更新された直後に不要なカメラ移動（ズームリセットを含む）を
  // 起こさないようにするためのワンショットフラグ（dragendハンドラでtrueに立てる）。
  const skipNextFlyToRef = useRef(false);
  const redrawPropsRef = useRef({
    routes,
    selectedRouteId,
    routeLayerOn,
    spliceStretches,
    splicedRoute,
    routeStyleModes,
    routeStyleModeId,
    hiddenRouteLegendKeys,
    showElevation,
    showLandcover,
    dynamicWeather,
    showRoadType,
    showRoadSurface,
    showDesignation,
    showTunnel,
    showOneway,
    dedicatedWayValueVisibility,
    showAccidents,
    showStopPoi,
    showSupplyPoi,
    axisVisibility,
    roadHiddenKeysByMode,
    staticLegendHiddenKeysByAxis,
    experimentSlots,
    staticOverlayLayers,
    staticFilterAxes,
    roadSurfaceSharedLayerIds,
    dedicatedWayValues,
  });

  const selectedCandidate = routes.find((r) => r.id === selectedRouteId) ?? null;

  useEffect(() => {
    onRegionZoomHintChangeRef.current = onRegionZoomHintChange;
  }, [onRegionZoomHintChange]);

  useEffect(() => {
    onViewportChangeRef.current = onViewportChange;
  }, [onViewportChange]);

  useEffect(() => {
    onLayerDataStatusChangeRef.current = onLayerDataStatusChange;
  }, [onLayerDataStatusChange]);

  useEffect(() => {
    onPinPlaceRef.current = onPinPlace;
  }, [onPinPlace]);

  useEffect(() => {
    armedPinRoleRef.current = armedPinRole;
  }, [armedPinRole]);

  useEffect(() => {
    pointEditingEnabledRef.current = pointEditingEnabled;
  }, [pointEditingEnabled]);

  useEffect(() => {
    onWaypointRemoveRef.current = onWaypointRemove;
  }, [onWaypointRemove]);

  useEffect(() => {
    onWaypointMoveRef.current = onWaypointMove;
  }, [onWaypointMove]);

  useEffect(() => {
    onDestinationClearRef.current = onDestinationClear;
  }, [onDestinationClear]);

  useEffect(() => {
    onOriginSetRef.current = onOriginSet;
  }, [onOriginSet]);

  useEffect(() => {
    routeFitObscuredPxRef.current = routeFitObscuredPx;
  }, [routeFitObscuredPx]);

  useEffect(() => {
    onRouteSegmentSelectRef.current = onRouteSegmentSelect;
  }, [onRouteSegmentSelect]);

  useEffect(() => {
    onRouteSelectRef.current = onRouteSelect;
  }, [onRouteSelect]);

  useEffect(() => {
    onSpliceStretchSelectRef.current = onSpliceStretchSelect;
  }, [onSpliceStretchSelect]);

  useEffect(() => {
    redrawPropsRef.current = {
      routes,
      selectedRouteId,
      routeLayerOn,
      spliceStretches,
      splicedRoute,
      routeStyleModes,
      routeStyleModeId,
      hiddenRouteLegendKeys,
      showElevation,
      showLandcover,
      dynamicWeather,
      showRoadType,
      showRoadSurface,
      showDesignation,
      showTunnel,
      showOneway,
      dedicatedWayValueVisibility,
      showAccidents,
      showStopPoi,
      showSupplyPoi,
      axisVisibility,
      roadHiddenKeysByMode,
      staticLegendHiddenKeysByAxis,
      experimentSlots,
      staticOverlayLayers,
      staticFilterAxes,
      roadSurfaceSharedLayerIds,
      dedicatedWayValues,
    };
  }, [
    routes,
    selectedRouteId,
    routeLayerOn,
    spliceStretches,
    splicedRoute,
    routeStyleModes,
    routeStyleModeId,
    hiddenRouteLegendKeys,
    showElevation,
    showLandcover,
    dynamicWeather,
    showRoadType,
    showRoadSurface,
    showDesignation,
    showTunnel,
    showOneway,
    dedicatedWayValueVisibility,
    showAccidents,
    showStopPoi,
    showSupplyPoi,
    axisVisibility,
    roadHiddenKeysByMode,
    staticLegendHiddenKeysByAxis,
    staticOverlayLayers,
    staticFilterAxes,
    roadSurfaceSharedLayerIds,
    experimentSlots,
    dedicatedWayValues,
  ]);

  // 再描画の中身はモジュールレベルの`redrawAllLayers`が持つ（テストから実物を呼べる形に
  // するため）。ここはrefが保持する最新値を渡すだけの薄い包み。
  const redrawFromCurrentProps = useCallback((map: MapLibreMap) => {
    redrawAllLayers(map, {
      ...redrawPropsRef.current,
      inspectedWayId: inspectedWayIdRef.current,
      onRegionZoomHintChange: onRegionZoomHintChangeRef.current,
    });
  }, []);

  // レイヤーデータ状態（loading/empty/error）の状態管理・再計算はuseLayerDataStatusに
  // 集約されている。ここでは「今の表示ON/OFFフラグをどう読むか」だけを
  // 安定した関数として渡す（redrawPropsRef自体を渡さないのは、フック側をrefの内部構造に
  // 依存させないため）。
  const getLayerVisibility = useCallback(() => {
    const {
      showElevation,
      showLandcover,
      showRoadType,
      showRoadSurface,
      showDesignation,
      showTunnel,
      showOneway,
      showAccidents,
      showStopPoi,
      showSupplyPoi,
      axisVisibility,
    } = redrawPropsRef.current;
    return {
      elevation: showElevation,
      landcover: showLandcover,
      roadType: showRoadType,
      roadSurface: showRoadSurface,
      designation: showDesignation,
      tunnel: showTunnel,
      oneway: showOneway,
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
    onChangeRef: onLayerDataStatusChangeRef,
  });

  // JMA動的タイルの在否インデックスを定期取得し、空と分かっているタイルの要求を
  // 間引く（jmaTileProtocol.ts）。取得できていない間は間引きが効かないだけで表示は成立する。
  useJmaTileIndex();

  // 地図初期化
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    // JMAタイルの在否インデックスによる要求の間引き（jmaTileProtocol.ts）。Mapを作る前に
    // 登録する必要がある（スタイル適用時点でタイル要求が始まりうるため）。
    registerJmaTileProtocol();

    // アンマウント後にidleイベントが届いてもsetStateしないためのガード
    // （BackendStatusのcancelledガードと同じ考え方）
    let cancelled = false;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: mapStyleUrl(),
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
    // それまでの間は他のUI（レイヤーチップ等）と重なって読みにくくなる。AttributionControl
    // 自身と同じイベント（styledata/sourcedata）を購読し、都度コンパクト表示
    // （アイコンのみ）へ揃える（「変わらないデータを更新」によるsetStyle再読み込み時の
    // 再発にも同じ仕組みで対応できる）。
    const attribEl = mapContainerRef.current?.querySelector(".maplibregl-ctrl-attrib");
    function collapseAttribution() {
      attribEl?.classList.remove("maplibregl-compact-show");
    }
    map.on("styledata", collapseAttribution);
    map.on("sourcedata", collapseAttribution);

    // MapLibre自体もコンテナの内蔵ResizeObserverでの自動追従を持つが、デバッグモード時は
    // デバッグログの流入（タイル要求ごとにdebugLog→DebugConsole再レンダー→自動スクロール、
    // モバイルのisMobile確定に伴うレイアウト変化と重なる）が内蔵ResizeObserverの通知を
    // 取りこぼし、地図が画面幅の一部にしか描画されず残りが黒くなることがある
    // （キャンバスのCSS幅がコンテナ幅より狭い値に固定されたまま更新されない）。
    // 「コンテナの実サイズ変化を検知したら明示的にmap.resize()する」独自の
    // ResizeObserverを、内蔵の自動追従に上乗せする形で持たせる。
    const resizeObserver = new ResizeObserver(() => {
      mapRef.current?.resize();
    });
    resizeObserver.observe(mapContainerRef.current);
    // 標高ラスタ・路面ベクタタイルは他の重ね描きレイヤーより先に追加し、常に背景寄りに
    // 描画されるようにする（標高が最背面、その上に路面、さらに上にルート系レイヤー）。
    // ensureAllStaticOverlayLayers内のdesignation/ramp軸はROAD_TILE_SOURCE_ID
    // （road_surfaceベクタソース）を再利用する依存関係があるため、そのソースを実際に作る
    // ensureRoadSurfaceTileLayerを先に呼ぶ必要がある。いずれも初回はmap.once("load", ...)への
    // 登録（実行はスタイル読み込み完了後）のため、ここでの呼び出し順がそのまま発火順になる。
    // ensureAllStaticOverlayLayersをensureRoadSurfaceTileLayerより先に呼ぶと、
    // designation等のaddLayerがソース未作成のまま実行され
    // 「source "region-road-surface-tiles" not found」エラーになる。標高を先に単独ensureして
    // から路面ソースを作ることで「標高が最背面、その上に路面」の意図を保つ
    // （ensureAllStaticOverlayLayers内でelevationが二重に呼ばれるが自身のガードで
    // 無害化される）。
    // staticOverlayLayersはredrawPropsRef.current経由で読む（このeffectは
    // マウント時のみ実行され、propsのrampAxesが後から変わっても再実行されないため。
    // 実行時フェッチで新しい軸が現れた場合の追従は、別途staticOverlayLayers変更時の
    // effectで対応する）。
    redrawPropsRef.current.staticOverlayLayers.find((layer) => layer.key === "elevation")?.ensure(map);
    ensureRoadSurfaceTileLayer(map);
    ensureAllStaticOverlayLayers(map, redrawPropsRef.current.staticOverlayLayers);

    // 路面レイヤーの区間・ルートレイヤーの詳細区間をクリックすると詳細をポップアップ表示する
    // （標高はラスタタイルのため、地物ごとのクリック判定は行わない）。**どれかの役割で武装して
    // いる間だけ**、その1タップは地物ヒット判定を迂回してピンを置く（道路の上を目的地に
    // したい場合もあるため）。武装していなければ地図を触ってもピンは増えない——役割を選ばずに
    // 置けると、地図を見ているだけのつもりの操作で経由地が増える。出発地点はマーカー自身の
    // ドラッグでも動かせる（下部のuseEffect）。
    function handleClick(e: MapMouseEvent) {
      const armed = armedPinRoleRef.current;
      if (armed) {
        onPinPlaceRef.current(armed, { latitude: e.lngLat.lat, longitude: e.lngLat.lng });
        return;
      }
      // ルート線（当たり判定はDETAIL_HIT_LAYER_ID）は下の
      // handleRouteSegmentClickという専用ハンドラを別途
      // map.on("click", DETAIL_HIT_LAYER_ID, ...)で登録している。MapLibreはmap全体の
      // genericな"click"（このhandleClick）とlayer-scopedな"click"を互いに独立して
      // 両方発火するため、ここで何もガードしないとルート線をクリックしたときに専用ハンドラの
      // マーカー表示・区間選択と、この下の一般道路網向けポップアップが同時に開いてしまう
      // （ルート線は常にroad_surfaceタイルより上に重ねて描画される、drawDetailSegments参照）。
      // ルート線がヒットした場合はここで即座に抜け、一般道路網側の判定・ポップアップ表示を
      // 一切行わない。
      // 候補線（ROUTES_HIT_LAYER_ID）も同じ理由で専用ハンドラ（handleCandidateClick）を
      // 持つため、一般道路網向けのポップアップは開かない。
      for (const hitLayerId of [DETAIL_HIT_LAYER_ID, ROUTES_HIT_LAYER_ID, SPLICE_HIT_LAYER_ID]) {
        if (map.getLayer(hitLayerId) && map.queryRenderedFeatures(e.point, { layers: [hitLayerId] }).length > 0) {
          return;
        }
      }
      const layers = interactiveLayerIdsRef.current.filter((id) => map.getLayer(id));
      if (layers.length === 0) return;
      const features = map.queryRenderedFeatures(e.point, { layers });
      if (features.length === 0) return;

      const feature = features[0];
      // 道路は「この道は何者で、なぜこの評価なのか」に答える面のため、ルート結果と同じ
      // React部品（RoadInspectorPopup）で描く。HTML文字列を組み立てる方式だと、同じ
      // 「軸ごとの効き方」を別の見た目で見せることになる。点データ（事故・POI）は
      // 1〜3行の事実だけなのでHTMLのまま。
      const html =
        feature.layer.id === ACCIDENT_LAYER_ID
          ? buildAccidentPopupHtml(feature.properties as unknown as AccidentPopupProperties)
          : feature.layer.id === STOP_POI_LAYER_ID
            ? buildPoiPopupHtml("停止要因", STOP_POI_LABELS, feature.properties as unknown as PoiPopupProperties)
            : feature.layer.id === SUPPLY_POI_LAYER_ID
              ? buildPoiPopupHtml("補給・休憩", SUPPLY_POI_LABELS, feature.properties as unknown as PoiPopupProperties)
              : null;

      popupRef.current?.remove();
      popupRef.current = null;
      if (html !== null) {
        setRoadPopup(null);
        popupRef.current = new maplibregl.Popup({ closeButton: true }).setLngLat(e.lngLat).setHTML(html).addTo(map);
        return;
      }
      setRoadPopup({
        lngLat: [e.lngLat.lng, e.lngLat.lat],
        properties: feature.properties as unknown as RoadSurfacePopupProperties,
      });
    }

    // ルート線専用のクリックハンドラ。MapLibreのlayer-scoped listener
    // （map.on(type, layerId, listener)）を使い、上のhandleClick（一般道路網向け、複数レイヤーを
    // queryRenderedFeaturesで横断判定する汎用ディスパッチャ）とは別経路として独立させている。
    // DETAIL_HIT_LAYER_IDがまだstyleに追加されていない（ルート未生成）間はMapLibre側が内部で
    // existingLayersを毎回フィルタしており、レイヤー不在でも例外を投げず単に発火しない
    // （maplibre-gl-dev.js: Map.prototype._createDelegatedListener参照）ため、地図初期化時に
    // 先読み登録しても安全。feature.properties（RouteSegmentDetailのgeometry除いた形、
    // segmentsToFeatureCollectionが焼き込み済み）をそのまま使い、サーバーへの新規リクエストは
    // 発生させない。
    // 候補線（当たり判定はROUTES_HIT_LAYER_ID）を押したら、その候補を選ぶ。選択中候補は
    // DETAIL_LAYER_ID側が区間の詳細を持つため、こちらは未選択候補への乗り換えだけを担う。
    function handleCandidateClick(e: MapLayerMouseEvent) {
      const routeId = e.features?.[0]?.properties?.routeId;
      if (typeof routeId !== "string") return;
      popupRef.current?.remove();
      onRouteSelectRef.current(routeId);
    }

    // 乗り換えられる区間の帯を押したら、その区間の道を選ぶ（選ぶ操作の中心を地図へ置く）。
    function handleSpliceStretchClick(e: MapLayerMouseEvent) {
      const index = e.features?.[0]?.properties?.index;
      if (typeof index !== "number") return;
      popupRef.current?.remove();
      onSpliceStretchSelectRef.current?.(index);
    }

    function handleRouteSegmentClick(e: MapLayerMouseEvent) {
      const feature = e.features?.[0];
      if (!feature) return;
      // 一般道路網向けの詳細ポップアップ（popupRef、handleClick側）と
      // 同時に開いた状態が残らないよう、こちらも既存のポップアップを閉じる
      // （このハンドラ自体はもうポップアップを開かないが、以前のクリックで開いたままの
      // ポップアップが残っていれば片付ける）。
      popupRef.current?.remove();
      const rawProperties = feature.properties as unknown as RouteSegmentProperties;
      const segment: RouteSegmentDetail = { ...restoreRouteSegmentProperties(rawProperties), geometry: null };
      // 当たり判定（DETAIL_HIT_LAYER_ID、幅24px）は見た目の線
      // （6px）より広いため、クリック地点をそのまま使うとマーカーがルート線から目に
      // 見えてズレる。区間のgeometry（LineString）上の最近点へ補正する
      // （nearestPointOnLineString参照）。geometryが無い/空の異常系はクリック地点
      // そのままへフォールバックする。
      const geometry = feature.geometry as GeoJSON.Geometry | undefined;
      const lineCoordinates = geometry?.type === "LineString" ? (geometry.coordinates as [number, number][]) : [];
      const [snappedLng, snappedLat] =
        lineCoordinates.length > 0
          ? nearestPointOnLineString(lineCoordinates, [e.lngLat.lng, e.lngLat.lat])
          : [e.lngLat.lng, e.lngLat.lat];
      // 地図上はテキストポップアップを出さず、クリック地点（上記の補正後）へ
      // 軽量なマーカーのみ立てる（下部の`selectedRouteSegment`監視useEffectが実際の
      // マーカー表示を担う、destinationMarkerと同じcontrolled propパターン）。区間の地点・
      // 到達予想時刻・軸別内訳（積み上げバー）はすべてボトムシート側
      // （page.tsx: selectedRouteSegment state、RouteAxisProfile）が表示する。
      onRouteSegmentSelectRef.current({ segment, latitude: snappedLat, longitude: snappedLng });
    }

    function handleMouseMove(e: MapMouseEvent) {
      const layers = interactiveLayerIdsRef.current.filter((id) => map.getLayer(id));
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
      const {
        showRoadType,
        showRoadSurface,
        showDesignation,
        showTunnel,
        showOneway,
        axisVisibility,
        dedicatedWayValueVisibility,
        roadSurfaceSharedLayerIds,
      } = redrawPropsRef.current;
      updateRoadZoomHint(
        map,
        isRoadSurfaceGroupVisible(
          {
            showRoadType,
            showRoadSurface,
            showDesignation,
            showTunnel,
            showOneway,
            axisVisibility,
            dedicatedWayValueVisibility,
          },
          roadSurfaceSharedLayerIds,
        ),
        onRegionZoomHintChangeRef.current,
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
      // スタイル自体がまだ一度もreadyになっていない状態でのerrorは、個別タイルの一過性の
      // 失敗ではなくスタイル取得そのものの失敗である可能性が高い（runWhenStyleReadyが
      // 頼るmap.once("load", ...)がこの後発火しないままdrawBaseRoutes等の描画コールバックが
      // 永久にスキップされる）。デバッグモードに関わらずユーザーへ気づけるようにする。
      const tagged = map as unknown as { __rcStyleReady?: boolean };
      // __rcStyleReadyは初回ロード成功後は永久にtrueのままのため、それだけでは
      // 「変わらないデータを更新」によるsetStyle()の失敗を検知できない
      // （styleReloadPendingRef宣言のコメント参照）。両方のフラグのいずれかが
      // 「まだ有効なスタイルが無い」ことを示していればfatal扱いにする。
      const isFatal = !tagged.__rcStyleReady || styleReloadPendingRef.current;
      // スタイル読み込み後に起きるerrorは、大半が個別タイル1枚の一過性の
      // 取得失敗（パン/ズーム中のキャンセル・瞬断等、次の取得サイクルで自然に解消する）
      // であり、上記の致命的ケースと同列の"error"にすると常時ノイズになる。
      // 致命的か一過性かで"error"/"warn"を出し分ける。
      debugLog("map:error", e.error?.message ?? "unknown error", { sourceId }, isFatal ? "error" : "warn");
      if (isFatal) {
        setStyleLoadFailed(true);
        setInitialTilesLoading(false);
      }
      // レイヤーデータ状態の対象sourceで起きたエラーは「取得失敗」として記録する
      // （エラー解除はhandleTrackedSourceDataLoading側、新しい取得サイクルの開始時のみ）。
      if (sourceId) markSourceErrored(sourceId);
    }
    function handleFirstIdle() {
      if (cancelled) return;
      setInitialTilesLoading(false);
      recomputeLayerDataStatus();
      // 初回表示時点のビューポートも伝える（ユーザーが一度もパン/ズームしなくても
      // 風の詳細格子等が初期位置に対して取得できるようにするため）。
      reportViewport();
    }
    // レイヤーデータ状態の対象sourceのタイル取得イベント。新しい取得サイクルの
    // 開始（sourcedataloading）で直前のエラー状態をクリアし、進行・完了（sourcedata）の
    // たびに再計算する（loading/empty/errorいずれも、実際の変化がなければ
    // recompute内でコールバックを呼ばない）。
    function handleTrackedSourceDataLoading(e: maplibregl.MapSourceDataEvent) {
      clearSourceLoading(e.sourceId);
    }
    function handleTrackedSourceData(e: maplibregl.MapSourceDataEvent) {
      notifySourceData(e.sourceId);
    }
    // 風の詳細格子（ヒートマップ用）等、「今見えている範囲だけ」を対象に
    // フェッチしたいレイヤーへビューポートを伝える。デバウンス・ズーム閾値判定は
    // 呼び出し側（page.tsx）の責務とし、ここでは素直に現在値を都度渡すだけにする。
    function reportViewport() {
      const bounds = map.getBounds();
      if (!bounds) return;
      onViewportChangeRef.current({
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
    // MapLibreのMap#resize()（ResizeObserver経由、上記参照）はmap内部が既に移動中
    // （慣性スクロール中等、_moving=true）のときmovestart/move/moveendの発火を意図的に
    // 抑止し、"resize"イベントのみを発火する。このタイミングでリサイズが起きると、
    // moveend/zoomendしか見ていないreportViewportが呼ばれずboundsが古いまま固定され、
    // 環境グループのgridFill・専用way値配信軸等viewportデバウンス経由でタイル範囲を決める
    // レイヤーが、新しく見えるようになった領域（典型的には画面右端）を塗らないまま残る。
    function handleResize() {
      debugLog("map:viewport", "resize", { zoom: Number(map.getZoom().toFixed(2)) });
      settleViewport();
      reportViewport();
    }
    // isSourceLoaded()がtrueになった直後の一瞬は
    // querySourceFeatures()がまだ実際のフィーチャーを返さないタイミングがあり
    // （isSourceLoadedとタイルのパース完了の間に競合がある）、その瞬間にsourcedataイベントで
    // 再計算すると誤って"empty"と判定・確定してしまう。その後実際にフィーチャーが揃っても、
    // 状態を変える追加のsourcedataイベントが来ないため、誤ったempty表示のまま固定されうる。
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
    // （バックエンド障害中に"idle"で誤ってerrorが消え、"データなし"に化ける）。
    function handleIdleRecompute() {
      recomputeLayerDataStatus();
    }

    map.on("click", handleClick);
    // ルート線専用（layer-scoped）。上のhandleClick（generic）とは独立して両方このイベントで
    // 発火するため、handleClick冒頭のガードと対で機能する。
    map.on("click", DETAIL_HIT_LAYER_ID, handleRouteSegmentClick);
    map.on("click", ROUTES_HIT_LAYER_ID, handleCandidateClick);
    map.on("click", SPLICE_HIT_LAYER_ID, handleSpliceStretchClick);
    map.on("mousemove", handleMouseMove);
    map.on("zoom", handleZoom);
    map.on("load", handleLoad);
    map.on("error", handleMapError);
    map.on("moveend", handleMoveEnd);
    map.on("zoomend", handleZoomEnd);
    map.on("resize", handleResize);
    map.on("sourcedataloading", handleTrackedSourceDataLoading);
    map.on("sourcedata", handleTrackedSourceData);
    map.on("idle", handleIdleRecompute);
    map.once("idle", handleFirstIdle);
    // "idle"が来なくても上限で覆いを外す（INITIAL_TILES_OVERLAY_MAX_MSのコメント参照）。
    const initialOverlayTimer = window.setTimeout(handleFirstIdle, INITIAL_TILES_OVERLAY_MAX_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(initialOverlayTimer);
      resizeObserver.disconnect();
      map.off("styledata", collapseAttribution);
      map.off("sourcedata", collapseAttribution);
      map.off("click", handleClick);
      map.off("click", DETAIL_HIT_LAYER_ID, handleRouteSegmentClick);
      map.off("click", ROUTES_HIT_LAYER_ID, handleCandidateClick);
      map.off("click", SPLICE_HIT_LAYER_ID, handleSpliceStretchClick);
      map.off("mousemove", handleMouseMove);
      map.off("zoom", handleZoom);
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
      // markerRef/popupRefは破棄されたmapインスタンスに紐づいたままなのでリセットする。
      // リセットしないと、React Strict Modeの開発時二重マウント（mount→cleanup→mount）で
      // 1回目のmarkerが残ったまま2回目（実際に画面に残る方）のmapには一度も追加されず、
      // 以降locationが変わっても現在地マーカーが永久に表示されなくなる。
      markerRef.current = null;
      appliedMarkerSourceRef.current = null;
      popupRef.current = null;
      waypointMarkersRef.current = [];
      destinationMarkerRef.current = null;
      selectedSegmentMarkerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 位置が変わったら地図とマーカーを更新。出発地点マーカーはドラッグで
  // 動かせる（draggable）。dragendでonOriginSet（page.tsx:
  // setManualLocation）を呼び、位置・locationSourceを更新する。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const applyLocation = () => {
      // ドラッグ操作自体で既にその地点が画面内に見えているため、setManualLocation経由の
      // 更新直後はカメラ移動（ズームリセットを含む）をスキップする。
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
          draggable: pointEditingEnabledRef.current,
        })
          .setLngLat([location.longitude, location.latitude])
          .addTo(map);
        markerRef.current.on("dragend", () => {
          const lngLat = markerRef.current!.getLngLat();
          skipNextFlyToRef.current = true;
          onOriginSetRef.current({ latitude: lngLat.lat, longitude: lngLat.lng });
        });
        appliedMarkerSourceRef.current = locationSource;
      }
    };

    runWhenStyleReady(map, applyLocation);
  }, [location, locationSource]);

  // 経由地マーカーを更新（最大でも8件程度のため、差分更新はせず
  // 既存マーカーを全部remove→全部作り直す簡易実装）。出発地マーカー（#e11d48）とは
  // 別色（#2563eb）にし、番号で訪問順序を示す。つかんで動かせ、クリックで即削除する
  // （確認ダイアログなし、間違えてもすぐ打ち直せるため）。
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
            onWaypointMoveRef.current(index, { latitude: lngLat.lat, longitude: lngLat.lng });
          });
          bindDragAwareClick(marker, el, () => onWaypointRemoveRef.current(index));
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

  // 目的地マーカーを更新（最大1点）。経由地と同じ丸いバッジで、中身の旗が「終点」を示す。
  // つかんで動かせ、クリックで解除。
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
          onPinPlaceRef.current("destination", { latitude: lngLat.lat, longitude: lngLat.lng });
        });
        bindDragAwareClick(marker, el, () => onDestinationClearRef.current());
      }
      destinationMarkerRef.current = marker;
    };

    runWhenStyleReady(map, applyDestinationMarker);
  }, [destination, pointEditingEnabled]);

  // 区間クリックで選択中の区間があれば、クリック地点へ軽量なマーカーのみを
  // 立てる（テキストポップアップは出さない——地点・到達予想時刻・軸別内訳はボトムシート側
  // [RouteAxisProfile]が表示する）。destinationMarkerと同じcontrolled propパターン
  // （selectedRouteSegmentがnullになれば、page.tsx側の×ボタン操作・別候補への切り替え等
  // どの経路でクリアされてもここでマーカーが消える）。
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
        onRouteSegmentSelectRef.current(null);
      });
      selectedSegmentMarkerRef.current = new maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([selectedRouteSegment.longitude, selectedRouteSegment.latitude])
        .addTo(map);
    };

    runWhenStyleReady(map, applySelectedSegmentMarker);
  }, [selectedRouteSegment]);

  // ルート候補のベース表示・選択中候補のハロー表示をまとめて更新する。候補線用・
  // ハロー用に別々のeffectを持たせてそれぞれがif(routeLayerOn)分岐を手書きすると、
  // redrawAllLayers側にも同じ分岐を書く必要が生じ、書き忘れるとrouteLayerOn（地図上
  // 「ルート」チップ）をOFFにしても候補線・ハロー・矢印が消えない不整合になる。
  // applyRouteLayerVisibility（MapView.tsx上部で定義）へ集約し、この1effectと
  // redrawAllLayersの両方から同じ関数を呼ぶことで、呼び出し元が増えても分岐の
  // 書き忘れが起きない構造にする。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    applyRouteLayerVisibility(map, routeLayerOn, routes, selectedRouteId, Boolean(selectedCandidate?.segments));
  }, [routes, selectedRouteId, routeLayerOn, selectedCandidate]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applySpliceLayerVisibility(map, routeLayerOn, spliceStretches, splicedRoute);
  }, [spliceStretches, splicedRoute, routeLayerOn]);

  // 表示範囲のフィットは「候補一覧が変わったとき」だけに限定する。
  // selectedRouteIdを依存に含めると、候補選択の切り替えのたびに（fitBoundsToRoutesは
  // routesしか使わず選択候補に寄せるわけでもないのに）地図が全候補の範囲へ強制的に
  // リセットされてしまい、ユーザーが選択後に手動でズーム/パンした操作を打ち消してしまう。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (routes.length > 0) {
      fitBoundsToRoutes(map, routes, routeFitObscuredPxRef.current);
    }
  }, [routes]);

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
      drawDetailSegments(
        map,
        selectedCandidate.segments,
        getRouteStyleMode(routeStyleModes, routeStyleModeId),
        hiddenRouteLegendKeys,
      );
    } else {
      hideDetailSegments(map);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routes, selectedRouteId, routeLayerOn, routeStyleModes, routeStyleModeId, hiddenRouteLegendKeys]);

  // 標高・指定路線・事故・ramp軸等は、いずれも「選択候補に関係なく地図全体に重ね描きし、
  // 切替はvisibilityの差し替えのみ」という同型のレイヤー（staticOverlayLayersが並べる）の
  // ため、1つのeffectでまとめて反映する
  // （setLayerVisibilityは同じ値の再設定でも副作用が無いため、
  // いずれか1つのフラグが変わったときに他を再設定しても表示に影響しない）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    setStaticOverlayVisibility(
      map,
      {
        elevation: showElevation,
        landcover: showLandcover,
        designation: showDesignation,
        tunnel: showTunnel,
        oneway: showOneway,
        ...dedicatedWayValueVisibility,
        accidents: showAccidents,
        stopPoi: showStopPoi,
        supplyPoi: showSupplyPoi,
        ...axisVisibility,
      },
      staticOverlayLayers,
    );
    // OFF→ONで新たに可視になったレイヤー、またはOFFになったレイヤーの状態表示を
    // 即座に反映する（タイルが既にキャッシュ済みでsourcedataイベントが発火しない場合でも
    // 状態が更新されるようにするため）。
    recomputeLayerDataStatus();
  }, [
    showElevation,
    showLandcover,
    showDesignation,
    showTunnel,
    showOneway,
    dedicatedWayValueVisibility,
    showAccidents,
    showStopPoi,
    showSupplyPoi,
    axisVisibility,
    recomputeLayerDataStatus,
    // staticOverlayLayersが変わる（軸スタジオの実行時フェッチで新しい軸が現れる・
    // 材料の表示切替でramp軸の下敷き表現が変わる）たびにsetStaticOverlayVisibility経由で
    // ensure()が再実行され、新しい軸のレイヤーもここで初めて登録される。
    staticOverlayLayers,
  ]);

  // way_id→動的値配信層（風=wind_drag_ratio・勾配=effective_gradient）。
  // hooks/useDedicatedWayValues.tsが現在のビューポートに対して取得した値を
  // MapLibreのsetFeatureStateへ反映する。上のSTATIC_OVERLAY_LAYERS一括effect（表示ON/OFFの
  // 切替）とは別のeffectにする理由は動的気象レイヤーと同じ——dedicatedWayValuesはパン・
  // ズームのたびに変わりうる値のため、他のshow*系フラグ群と同居させると無関係な再実行が
  // 増える。どの軸も表示されていない間も値自体はhooks側でenabled=falseにより
  // 空のMapへ戻るため、ここでは値をそのまま反映するだけで十分（非表示レイヤーへ
  // feature-stateを設定しても表示には影響しない）。dedicatedWayValues（axisId→値の汎用Map）を
  // 1つのループで回すため、動的材料が増えてもこのeffect自体の変更は不要。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    runWhenStyleReady(map, () => {
      for (const [axisId, values] of dedicatedWayValues) {
        applyAxisFeatureStateValues(map, dedicatedWayValueFeatureStateKey(axisId), values);
      }
    });
  }, [dedicatedWayValues]);

  // 専用way値配信軸が1つも表示されなくなった瞬間
  // （ルート確定・手動OFFいずれも含む）に、それまでの全道路ぶんのfeature-stateを明示的に
  // クリアする（clearRoadTileFeatureState参照）。`map.removeFeatureState({source,
  // sourceLayer})`はMapLibreの仕様上キー単位の選択的削除ができずソース丸ごと消えるため、
  // 複数の軸が同時ON（排他ドメインではない）の状態で1つだけをOFFにした瞬間にこの関数を
  // 呼ぶと、まだONのままの他の軸の色分けまで巻き添えで消えてしまう。全てfalseになるまで
  // クリアを遅らせることで、「まだONの軸を巻き添えにしない」かつ「最後の1つがOFFになったら
  // 必ずクリアされる」を両立する。マウント直後（全フラグの初期値がfalse）にも走るが、
  // その時点ではまだsetFeatureStateが1件も呼ばれていないため無害（空振り）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !shouldClearDedicatedWayValueFeatureState(dedicatedWayValueVisibility)) return;
    runWhenStyleReady(map, () => clearRoadTileFeatureState(map));
  }, [dedicatedWayValueVisibility]);

  // 動的気象レイヤー（降水ナウキャスト・風の矢印）。いずれもpayloadが地図上の時刻
  // スライダー操作のたびに変わるため、
  // 上のSTATIC_OVERLAY_LAYERS一括effect（依存が多く再実行コストの大きいshowX系フラグ群）とは
  // 分けた専用effectにまとめる（DYNAMIC_WEATHER_LAYER_IDSで回すため、要素が増えてもこの
  // effect自体は変わらない）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const id of DYNAMIC_WEATHER_LAYER_IDS) {
      applyDynamicWeatherState(map, id, DYNAMIC_WEATHER_RENDERERS[id], dynamicWeather[id]);
    }
    recomputeLayerDataStatus();
  }, [dynamicWeather, recomputeLayerDataStatus]);

  // 指定路線・停止要因POI・事故（当事者/重大度）・ramp軸等の絞り込み。道路情報の
  // フィルタ効果（下）と同じく、visibility/フィルタ式の差し替えのみで反映される。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    setStaticOverlayFilters(map, staticLegendHiddenKeysByAxis, staticOverlayLayers, staticFilterAxes);
  }, [staticLegendHiddenKeysByAxis, staticOverlayLayers, staticFilterAxes]);

  // 路面（道路の種類/路面の種類）ON/OFF・凡例フィルタの切替は、いずれも
  // visibility/paint/フィルタ式の差し替えのみで反映される（データ取得はMapLibreがパン/
  // ズームに応じて自動で行うため、明示的なfetchは不要）。色・太さ・線種は
  // showRoadSurface/showRoadTypeの組み合わせでapplyRoadLayerStateが都度再計算する
  // （固定ではなくなった、applyRoadLayerStateのコメント参照）。
  // regionZoomTooWide（ズーム範囲外の案内）はroad_surfaceタイルを共有するdesignation/
  // tunnel、およびramp軸・専用way値配信軸のON/OFFでも変わりうるため、いずれも依存配列に
  // 含めてフラグが変わるたびに再評価する（road自体はOFFのままdesignation等や軸レイヤー
  // だけONで表示範囲が広すぎる場合にも案内を出すため）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyRoadLayerState(map, showRoadSurface, showRoadType, roadHiddenKeysByMode);
    applyRoadMaterialTrackOffsets(map, {
      roadSurface: showRoadSurface,
      roadType: showRoadType,
      designation: showDesignation,
      tunnel: showTunnel,
      oneway: showOneway,
    });
    updateRoadZoomHint(
      map,
      isRoadSurfaceGroupVisible(
        {
          showRoadType,
          showRoadSurface,
          showDesignation,
          showTunnel,
          showOneway,
          axisVisibility,
          dedicatedWayValueVisibility,
        },
        roadSurfaceSharedLayerIds,
      ),
      onRegionZoomHintChangeRef.current,
    );
    recomputeLayerDataStatus();
  }, [
    showRoadType,
    showRoadSurface,
    showDesignation,
    showTunnel,
    showOneway,
    axisVisibility,
    dedicatedWayValueVisibility,
    roadHiddenKeysByMode,
    roadSurfaceSharedLayerIds,
    recomputeLayerDataStatus,
  ]);

  // 「地図の表示を再描画」ボタン: スタイルを取り直して地図を組み直す（押した人の地図
  // インスタンスだけに閉じた操作で、サーバー側のタイルキャッシュには触れない）。
  // setStyle()はカスタムレイヤーを消すため、style.load後にredrawAllLayersで全て描き直す。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || refreshToken === 0) return;
    // refreshTokenが短時間に連続変化した場合（連打）、複数のsetStyle呼び出しが重なることへの
    // ガード。MapLibreは新しいsetStyle呼び出しで前のスタイル読み込みを打ち切りうるため、
    // 1回目のstyle.loadリスナーが発火せずredrawAllLayersが一度も呼ばれない可能性がある。
    // 既に進行中（style.load未確定）ならこの呼び出しはスキップする。
    if (styleReloadPendingRef.current) return;
    styleReloadPendingRef.current = true;

    map.once("style.load", () => {
      styleReloadPendingRef.current = false;
      redrawFromCurrentProps(map);
    });
    // クエリでスタイルURLを変えることで、ブラウザのHTTPキャッシュではなく取り直しにする。
    map.setStyle(`${mapStyleUrl()}?t=${Date.now()}`);
  }, [refreshToken, redrawFromCurrentProps]);

  // 道路クリックの詳細ポップアップ。中身はReactで描き、MapLibreのPopupは器として使う。
  // 開いている間はその道を地図上で強調する（どの線の話かが分からないと詳細だけ見ても
  // 場所を取り違える）。強調は路面タイルのfeature-state（promoteIdでosm_way_idが
  // feature.idへ昇格済み）で行い、専用のソースや取得を増やさない。
  useEffect(() => {
    const map = mapRef.current;
    // 再描画（map.setStyle()）は強調を初期値へ戻すため、redrawAllLayersが復元できるよう
    // 開いている道をrefで持つ。早期returnより前に置き、閉じたときもnullへ戻す。
    inspectedWayIdRef.current = roadPopup?.properties.osm_way_id ?? null;
    if (!map || roadPopup === null) return;
    const container = document.createElement("div");
    const popup = new maplibregl.Popup({ closeButton: true, maxWidth: "20rem" })
      .setLngLat(roadPopup.lngLat)
      .setDOMContent(container)
      .addTo(map);
    setRoadPopupContainer(container);
    const wayId = roadPopup.properties.osm_way_id;
    runWhenStyleReady(map, () => {
      ensureRoadSurfaceTileLayer(map);
      applyInspectedWay(map, wayId ?? null);
    });
    const close = () => setRoadPopup(null);
    popup.on("close", close);
    return () => {
      popup.off("close", close);
      popup.remove();
      setRoadPopupContainer(null);
      applyInspectedWay(map, null);
    };
  }, [roadPopup]);

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
      {roadPopup !== null &&
        roadPopupContainer !== null &&
        createPortal(
          <RoadInspectorPopup properties={roadPopup.properties} axes={axes} axisColors={axisColors} />,
          roadPopupContainer,
        )}
    </div>
  );
}

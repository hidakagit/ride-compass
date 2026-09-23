"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  type AccidentPopupProperties,
  buildAccidentPopupContent,
  buildPoiPopupContent,
  type PoiPopupProperties,
} from "@/features/map/MapView/pointPopup";
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
  type MapLayerId,
} from "@/features/map/layers/mapLayers";
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
  ROUTE_HIT_TARGET_CANDIDATE,
  ROUTE_HIT_TARGET_SEGMENT,
  ROUTE_HIT_TARGET_SPLICE_BAND,
} from "@/features/map/scene/groups/routes";
import { buildMapScene, type SceneInputs } from "@/features/map/scene/buildScene";
import { POINT_LAYERS, pointSourceId } from "@/features/map/scene/groups/points";
import { AREA_SOURCE_ID } from "@/features/map/scene/groups/areaRasters";
import { ROAD_LINE_SOURCE_ID } from "@/features/map/scene/groups/roadLines";
import { sceneLayerId } from "@/features/map/scene/sceneBuilders";
import {
  restoreRouteSegmentProperties,
  type SerializedRouteSegmentProperties,
} from "@/features/map/routeSegmentProperties";

/** 押された点のレイヤーidから、その点の宣言を引く。idは役割から決まるので写しではない。 */
const POINT_LAYER_BY_SCENE_ID = new Map(
  POINT_LAYERS.map((layer) => [sceneLayerId(pointSourceId(layer.tile_kind), layer.attr_id), layer]),
);

/** 分類値→表示名。凡例と同じ宣言から引く。 */
function pointValueLabels(layer: (typeof POINT_LAYERS)[number]): Record<string, string> {
  const axis = layer.display_axes[0];
  if (axis === undefined) return {};
  return Object.fromEntries(
    axis.categories.flatMap((category) => category.values.map((value) => [String(value), category.label])),
  );
}

/** ルート線の当たり判定レイヤー。**idは scene が決める**ので、当たり判定の名前で引く。 */
function routeHitLayerId(scene: MapScene, target: string): string | undefined {
  return sceneLayerIdsForHitTarget(scene, target)[0];
}
import { axisMapLayerId } from "@/lib/mapDisplay/axisLayers";
import type { MapLook } from "@/features/map/view/mapLook";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { useTileVersionsReady } from "@/features/map/useTileVersionsReady";
import { useLayerDataStatus } from "@/features/map/MapView/useLayerDataStatus";
import { useJmaTileIndex } from "@/features/map/useJmaTileIndex";
import { registerJmaTileProtocol } from "@/features/map/layers/jmaTileProtocol";
import { debugLog } from "@/lib/debugLog";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

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
// として確定しないことがある（地図の上のボタンが同じ理由で持っている対策と同じもの）。
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

// payload（page.tsx側が各要素のデータ層関数から計算した値）を反映する。グループ配下の
// 各ソースについて、visibleとpayloadのどちらか一方でも欠けていれば非表示のまま（フェッチ
// 未完了・取得失敗時、あるいは選択時刻がそのソースのデータ範囲外で「描画しない」場合に、
// 古いフレームが一瞬見えるのを防ぐ）。payload.kindがそのソースのspecの複数サブレイヤー
// （precipitationNowcast.mainのraster/gridFill等）のどれと対応するかだけを見て、対応しない
// サブレイヤーは常に非表示にする（=同時に両方は出ない）。ソースをまたいだ複数payloadの
// 同時表示（precipitationNowcastのmain+linearRainband等）は、グループ内の別ソースとして
// 独立にvisible/payloadを持つことで実現する（このループ自体は各ソースを独立に処理するだけ）。

// interactive: クリック・カーソル判定（handleClick/handleMouseMove）の対象にするか。
// レイヤーを足すときにその場で答えさせるため必須にしてある——別の一覧で「対象外のkey」を
// 数え上げる形にすると、新しいレイヤーが既定でクリック対象になり、「カーソルは
// クリック可能を示すのに実際は何も起きない」という不整合が静かに増える。

type LayerDataSource = { key: MapLayerId; sourceId: string; sourceLayer?: string };

// 情報源の名前（`MapLayerDataSource`）→ 実際のMapLibreの(source, source-layer)。
// **レイヤーごとではなく情報源ごとの表**で、新しい配信元を増やしたときだけ伸びる
// （どのレイヤーがどれを読むかは記述子側の宣言）。同じタイルを読むレイヤーが
// 同時にempty/errorになるのは正しい振る舞い（road_edgesが未構築の地点）。
// 国土地理院のラスタタイル・土地被覆ラスタはsource-layerを持たないため、取得失敗のみ
// 検知しempty判定はしない。
// 地図へ常時出す出典（AttributionControlのcustomAttribution）。MapLibreがソースへ渡した
// attributionを出すのは**そのソースが地図に載っている間だけ**で、レイヤーのON/OFFで消える。
// ここに挙げるデータは路面タイルへ焼き込むか評価軸・ルートの計算に常時使っており、どの
// レイヤーを表示しているかと関係なく出典が要る。地理院・警察庁の公共データ利用規約（PDL1.0）
// は出典とは別に加工した旨の記載を求めており、標高タイルからは勾配を、事故点からは区間ごとの
// 件数を導いている。基礎地図（OpenFreeMap / OpenMapTiles）はここへ入れない——配信元の
// TileJSONがattributionを持ち、MapLibreが同じ場所へ出す。
const MAP_BASE_ATTRIBUTION = [
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>',
  '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noreferrer">地理院タイル(標高タイル)</a>を加工して作成',
  "交通事故統計情報（警察庁）を加工して作成",
  '土地被覆: <a href="https://livingatlas.arcgis.com/landcover/" target="_blank" rel="noreferrer">Esri, Impact Observatory, Microsoft</a> (CC BY 4.0)',
];

// 初期表示の覆い（「地図を読み込み中…」）を出しておく上限。覆いは最初の数秒の白紙を
// 隠すためのもので、それを過ぎても残ると、描けている地図を隠して壊れているように見せる。
// MapLibreの"idle"は表示中のすべての取得が落ち着くまで来ないため、外部データ
// （既定ONの災害タイル等）が遅いセッションでは待ち続けてしまう。
const INITIAL_TILES_OVERLAY_MAX_MS = 6000;

const TILE_SOURCE_BY_DATA_SOURCE: Record<
  Exclude<MapLayerDataSource, "ownFetch">,
  { sourceId: string; sourceLayer?: string }
> = {
  roadTiles: { sourceId: ROAD_LINE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER },
  accidentTiles: { sourceId: pointSourceId("accident"), sourceLayer: ACCIDENT_TILE_SOURCE_LAYER },
  poiTiles: { sourceId: pointSourceId("poi"), sourceLayer: STOP_POI_SOURCE_LAYER },
  gsiRelief: { sourceId: AREA_SOURCE_ID.elevation },
  gsiTerrain: { sourceId: AREA_SOURCE_ID.hillshade },
  landcoverRaster: { sourceId: AREA_SOURCE_ID.landcover },
};

/** レイヤーごとのデータ取得状態の算出元。母集団はレイヤーカタログそのもので、
 * ここでは数え上げない——名指しで並べると、新しいレイヤーはここへ書き足すまで
 * 取得状態を持たず、チップの状態ドットが永久に出ない。
 *
 * 自前のJSで取りに行くもの（`ownFetch`。動的気象レイヤー・ルート）は除く——MapLibreの
 * ソースイベントはその待ち時間・失敗を観測できない（`useDynamicWeatherLayers.ts`が
 * フェッチ自身のloading/errorから出す）。 */
export function buildLayerDataSources(layers: readonly MapLayerDescriptor[]): readonly LayerDataSource[] {
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

// 区間クリックの当たり判定（sceneの役割`detailHit`、幅24px）は見た目の線（6px）より広いため、
// クリック地点（e.lngLat）をそのままマーカー位置に使うと、ルート線から目に見えてズレた
// 場所にマーカーが立ってしまう。クリックされた区間のgeometry（LineString）上で
// クリック地点にもっとも近い点を求め、そちらをマーカー位置として使う
// （handleRouteSegmentClick参照）。区間規模の距離感での見た目上のスナップが目的のため、
// 球面上の正確な最近点ではなく経緯度を平面とみなした単純な線分への垂線ベースの近似で十分
// （道路レベルのローカルな距離では誤差は無視できる）。
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

// ルート線クリック時、区間クリックは軽量なマーカーのみを地図上に立て、地点・到達予想
// 時刻・軸別の内訳（積み上げバー、AxisContributionBar）はすべてボトムシート側
// （page.tsx: selectedRouteSegment state、RouteAxisProfile）が表示する
// （handleRouteSegmentClick参照）。地図上にフローティングポップアップでレーダーチャートを
// 出す方式は、モバイルで「ルート結果」ボトムシートに隠れる・軸数が少ないとレーダーが
// 機能しない問題があるため採らない。

export interface MapViewProps {
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
  /** 出発地点マーカーの色分けに使う。GPS取得失敗時のフォールバック（"default"）だけを
   * グレーで視覚的に区別する。実際のGPS取得（"geolocation"）と手動指定（"manual"）は
   * どちらも「意図した位置」という点で同格のため、赤で区別しない。 */
  locationSource: LocationSource;
  /** 地図の見え方（`features/map/view/useMapView`）。状態そのものと地図からのイベントだけで、
   * 軸カタログ・タイル世代のような共有の源泉から導けるものはここで読む。 */
  look: MapLook;
  /** 地図が今指定している走行の条件（走行方位・時刻・想定速度）。専用way値配信軸が地図を
   * 塗るのに使っているものと同じ値を、道をクリックしたときの内訳
   * （RoadInspectorPopup）へも渡す——揃えないと同じ場所で色と数字が食い違う。 */
  rideConditions?: RideConditions;
  /** 実験スロット（研究インターフェース改善 §10-3）。デバッグモードOFF時は呼び出し側が
   * 空配列を渡すため、通常利用ではレイヤーは作られない。 */
  experimentSlots: ExperimentSlot[];
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
  /** 地図キャンバスの上に重なるUI（モバイルの下部タブバー・ボトムシート）で覆われている
   * 辺ごとの高さ(px)を、いま測って返す。ルート生成直後のフィットで、覆われた領域の中へルートが
   * 収まってしまうのを防ぐ。MapViewはシート・タブバーの存在を知らないため、レイアウトを持つ
   * 呼び出し側が測る。 */
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
  experimentSlots,
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
  measureRouteFitObscuredPx,
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
    // 押した瞬間のタイル。あとで地図のズームから出し直すと、ポップアップを開いたまま
    // ズームした場合に押した道と違うタイルを指す。
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
  // 詳細を見ている道（ポップアップが開いている間だけ非null）。強調も scene の一部として
  // 当てるため、状態から導く。
  const inspectedWayId = roadPopup?.properties.osm_way_id ?? null;
  // 地図に載るもの全部の入力。**ここが scene の唯一の組み立て口**で、家族ごとの
  // 個別の反映経路を持たない。
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
  // スタイルの差し替え後に作り直すとき、その時点の宣言を読む。
  const sceneRef = useRef(scene);
  useEffect(() => {
    sceneRef.current = scene;
  }, [scene]);
  // handleClick/handleMouseMove（地図初期化effect内、一度だけ登録されるクロージャ）が
  // 最新のinteractiveLayerIdsを読めるようにするref（onViewportChangeRef等と同じ
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
  const onViewportChangeRef = useRef(look.onViewportChange);
  const onLayerDataStatusChangeRef = useRef(look.onLayerDataStatusChange);
  // handleClick（地図初期化effect内、一度だけ登録されるクロージャ）が
  // 最新のonPinPlace・武装中の役割を読めるようにするref（onViewportChangeRefと同じパターン）。
  const onPinPlaceRef = useRef(onPinPlace);
  const armedPinRoleRef = useRef(armedPinRole);
  const pointEditingEnabledRef = useRef(pointEditingEnabled);
  const onWaypointRemoveRef = useRef(onWaypointRemove);
  const onWaypointMoveRef = useRef(onWaypointMove);
  // 同じ理由で目的地関連のコールバック・armed状態もrefで最新値を読む。
  const onDestinationClearRef = useRef(onDestinationClear);
  // 周回モード中は空白地点クリックでの経由地追加を行わない。
  // フィットは「候補一覧が変わったとき」だけに限る（下部のuseEffect参照）ため、覆われて
  // いる高さの変化（シートの開閉・高さドラッグ）でフィットをやり直さないようrefで読む。
  const measureRouteFitObscuredPxRef = useRef(measureRouteFitObscuredPx);
  // handleRouteSegmentClick（地図初期化effect内で一度だけ登録）が最新の
  // onRouteSegmentSelectを読めるようにするref。
  const onRouteSegmentSelectRef = useRef(onRouteSegmentSelect);
  const onRouteSelectRef = useRef(onRouteSelect);
  const onSpliceStretchSelectRef = useRef(onSpliceStretchSelect);
  // trueの間、位置更新effect（下部）がmap.flyTo（カメラ移動）をスキップする。
  // ドラッグ操作自体で既にその地点が画面内に見えているため、setManualLocation経由で
  // location/locationSourceが更新された直後に不要なカメラ移動（ズームリセットを含む）を
  // 起こさないようにするためのワンショットフラグ（dragendハンドラでtrueに立てる）。
  const skipNextFlyToRef = useRef(false);
  // 取得状態の再計算（地図イベントから呼ばれる）が、最新の表示ON/OFFを読むためのref。
  const layerVisibility = useMemo(
    () => ({
      ...look.layerVisibility,
      ...Object.fromEntries(
        catalog.rampAxes.map((axis) => [axisMapLayerId(axis.axisId), axis.axisId === look.paintedAxisId]),
      ),
    }),
    [look.layerVisibility, look.paintedAxisId, catalog.rampAxes],
  );
  const layerVisibilityRef = useRef(layerVisibility);

  useEffect(() => {
    onViewportChangeRef.current = look.onViewportChange;
    onLayerDataStatusChangeRef.current = look.onLayerDataStatusChange;
  }, [look.onViewportChange, look.onLayerDataStatusChange]);

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
    measureRouteFitObscuredPxRef.current = measureRouteFitObscuredPx;
  }, [measureRouteFitObscuredPx]);

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
    layerVisibilityRef.current = layerVisibility;
  }, [layerVisibility]);

  // スタイルを差し替えた後、いまの宣言を空から当て直す。
  const redrawFromCurrentProps = useCallback((map: MapLibreMap) => {
    applyScene(map, sceneRef.current, { reset: true });
  }, []);

  // レイヤーデータ状態（loading/empty/error）の状態管理・再計算はuseLayerDataStatusに
  // 集約されている。ここでは「今の表示ON/OFFフラグをどう読むか」だけを安定した関数として渡す。
  const getLayerVisibility = useCallback(() => layerVisibilityRef.current, []);
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

    // Workerの場所は、Mapを作る前に決める必要がある（Mapの生成がWorkerを起こす）。
    configureMaplibreWorker();

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
      attributionControl: { compact: true, customAttribution: MAP_BASE_ATTRIBUTION },
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
    // レイヤーは scene の適用（applyScene）が作る。ここでは作らない——2通りの経路で
    // 同じ地図を触ると、重なり順と表示が経路ごとに食い違う。

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
      // ルート線（当たり判定の的`ROUTE_HIT_TARGET_SEGMENT`）は下の
      // handleRouteSegmentClickという専用ハンドラを別途、当たり判定のレイヤーへ
      // map.on("click", layerId, ...)で登録している。MapLibreはmap全体の
      // genericな"click"（このhandleClick）とlayer-scopedな"click"を互いに独立して
      // 両方発火するため、ここで何もガードしないとルート線をクリックしたときに専用ハンドラの
      // マーカー表示・区間選択と、この下の一般道路網向けポップアップが同時に開いてしまう
      // （ルート線は常に路面タイルより上に重ねて描画される）。
      // ルート線がヒットした場合はここで即座に抜け、一般道路網側の判定・ポップアップ表示を
      // 一切行わない。
      // 候補線（的`ROUTE_HIT_TARGET_CANDIDATE`）も同じ理由で専用ハンドラ（handleCandidateClick）を
      // 持つため、一般道路網向けのポップアップは開かない。
      for (const hitLayerId of sceneLayerIdsForHitTarget(sceneRef.current, ROUTE_HIT_TARGET)) {
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
      // 1〜3行の事実だけなのでMapLibreのPopupへ直接載せる。
      const point = POINT_LAYER_BY_SCENE_ID.get(feature.layer.id);
      const pointContent =
        point === undefined
          ? null
          : point.attr_id === "accident_point"
            ? buildAccidentPopupContent(feature.properties as unknown as AccidentPopupProperties)
            : buildPoiPopupContent(
                point.label,
                pointValueLabels(point),
                feature.properties as unknown as PoiPopupProperties,
              );

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

    // ルート線専用のクリックハンドラ。MapLibreのlayer-scoped listener
    // （map.on(type, layerId, listener)）を使い、上のhandleClick（一般道路網向け、複数レイヤーを
    // queryRenderedFeaturesで横断判定する汎用ディスパッチャ）とは別経路として独立させている。
    // 当たり判定のレイヤーがまだstyleに追加されていない（ルート未生成）間はMapLibre側が内部で
    // existingLayersを毎回フィルタしており、レイヤー不在でも例外を投げず単に発火しない
    // （maplibre-gl-dev.js: Map.prototype._createDelegatedListener参照）ため、地図初期化時に
    // 先読み登録しても安全。feature.properties（RouteSegmentDetailのgeometry除いた形、
    // scene（features/map/scene/groups/routes.ts）が地物へ載せたもの）をそのまま使い、
    // サーバーへの新規リクエストは発生させない。
    // 候補線（的`ROUTE_HIT_TARGET_CANDIDATE`）を押したら、その候補を選ぶ。選択中候補は
    // 詳細区間（的`ROUTE_HIT_TARGET_SEGMENT`）側が区間の詳細を持つため、こちらは未選択候補への
    // 乗り換えだけを担う。
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
      const rawProperties = feature.properties as unknown as SerializedRouteSegmentProperties;
      const segment: RouteSegmentDetail = { ...restoreRouteSegmentProperties(rawProperties), geometry: null };
      // 当たり判定（sceneの役割`detailHit`、幅24px）は見た目の線
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
      // マーカー表示を担う、destinationMarkerRefと同じcontrolled propパターン）。区間の地点・
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
      // 頼るmap.once("load", ...)がこの後発火しないまま、そこで待たせた描画コールバックが
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
    // 専用ハンドラは当たり判定のレイヤーへ直接つなぐ（地図全体のclickと二重に発火させない）。
    const routeHitLayers = {
      segment: routeHitLayerId(sceneRef.current, ROUTE_HIT_TARGET_SEGMENT),
      candidate: routeHitLayerId(sceneRef.current, ROUTE_HIT_TARGET_CANDIDATE),
      spliceBand: routeHitLayerId(sceneRef.current, ROUTE_HIT_TARGET_SPLICE_BAND),
    };
    if (routeHitLayers.segment !== undefined) map.on("click", routeHitLayers.segment, handleRouteSegmentClick);
    if (routeHitLayers.candidate !== undefined) map.on("click", routeHitLayers.candidate, handleCandidateClick);
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
    // "idle"が来なくても上限で覆いを外す（INITIAL_TILES_OVERLAY_MAX_MSのコメント参照）。
    const initialOverlayTimer = window.setTimeout(handleFirstIdle, INITIAL_TILES_OVERLAY_MAX_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(initialOverlayTimer);
      resizeObserver.disconnect();
      map.off("styledata", collapseAttribution);
      map.off("sourcedata", collapseAttribution);
      map.off("click", handleClick);
      if (routeHitLayers.segment !== undefined) map.off("click", routeHitLayers.segment, handleRouteSegmentClick);
      if (routeHitLayers.candidate !== undefined) map.off("click", routeHitLayers.candidate, handleCandidateClick);
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

  // 位置が変わったら地図とマーカーを更新。出発地点マーカーはドラッグで動かせ（draggable）、
  // 目的地のマーカーと同じく、動かした先を「地点を置く」受け口（onPinPlace）へ渡す。
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
          onPinPlaceRef.current("origin", { latitude: lngLat.lat, longitude: lngLat.lng });
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
  // [RouteAxisProfile]が表示する）。destinationMarkerRefと同じcontrolled propパターン
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

  // 地図に載るもの（面・道路の線・評価軸・点・気象・ルート）は、1つの scene として
  // 組み立てて1本の経路で当てる。**表示・絞り込み・重なり順はすべてここを通る。**
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    applyScene(map, scene);
    // OFF→ONで新しく可視になったレイヤーの取得状態を即座に出す（タイルがキャッシュ済みで
    // sourcedataが発火しない場合でも状態が更新されるようにする）。
    recomputeLayerDataStatus();
  }, [scene, recomputeLayerDataStatus]);

  // 表示範囲のフィットは「候補一覧が変わったとき」だけに限定する。
  // selectedRouteIdを依存に含めると、候補選択の切り替えのたびに（fitBoundsToRoutesは
  // routesしか使わず選択候補に寄せるわけでもないのに）地図が全候補の範囲へ強制的に
  // リセットされてしまい、ユーザーが選択後に手動でズーム/パンした操作を打ち消してしまう。
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (routes.length > 0) {
      fitBoundsToRoutes(map, routes, measureRouteFitObscuredPxRef.current?.());
    }
  }, [routes]);

  // 「地図の表示を再描画」ボタン: スタイルを取り直して地図を組み直す（押した人の地図
  // インスタンスだけに閉じた操作で、サーバー側のタイルキャッシュには触れない）。
  // setStyle()はカスタムレイヤーを消すため、style.load後にいまの宣言を空から当て直す。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || look.refreshToken === 0) return;
    // refreshTokenが短時間に連続変化した場合（連打）、複数のsetStyle呼び出しが重なることへの
    // ガード。MapLibreは新しいsetStyle呼び出しで前のスタイル読み込みを打ち切りうるため、
    // 1回目のstyle.loadリスナーが発火せず作り直しが一度も走らない可能性がある。
    // 既に進行中（style.load未確定）ならこの呼び出しはスキップする。
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

  // 道路クリックの詳細ポップアップ。中身はReactで描き、MapLibreのPopupは器として使う。
  // 開いている間はその道を地図上で強調する（どの線の話かが分からないと詳細だけ見ても
  // 場所を取り違える）。強調は路面タイルを`osm_way_id`で絞る独立レイヤーで行い、
  // 専用のソースや取得を増やさない（区間単位のズームではそのwayの区間すべてが光る——
  // インスペクタが見せるのがway単位の属性のため）。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || roadPopup === null) return;
    const container = document.createElement("div");
    const popup = new maplibregl.Popup({ closeButton: true, maxWidth: "20rem" })
      .setLngLat(roadPopup.lngLat)
      .setDOMContent(container)
      .addTo(map);
    setRoadPopupContainer(container);
    const close = () => setRoadPopup(null);
    popup.on("close", close);
    return () => {
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
          <RoadInspectorPopup
            properties={roadPopup.properties}
            axes={catalog.axes}
            axisColors={catalog.axisColors}
            conditions={rideConditions != null ? { ...rideConditions, ...roadPopup.tile } : null}
          />,
          roadPopupContainer,
        )}
    </div>
  );
}

/** ルート候補・選択中ルート・区間色分け・乗り換え帯・比較スロットの地図描画。
 *
 * `MapView.tsx`から呼ばれる関数群で、`map`インスタンスを引数で受け取る（状態は持たない）。
 * ルートの見せ方が変わったときに一緒に変わるものをここへ集める。
 */
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import type { RouteCandidate, RouteSegmentDetail } from "@/types/route";
import type { ExperimentSlot } from "@/types/experimentSlot";
import type { RouteStyleMode } from "@/components/Map/routeStyleModes";
import { buildLegendFilterExpression } from "@/components/Map/legendFilter";
import { createRouteArrowIcon } from "@/components/Map/routeArrowIcon";
import { runWhenStyleReady, setLayerVisibility, zoomIconSizeExpression } from "@/components/Map/mapStyleOps";

const ROUTES_SOURCE_ID = "route-candidates";
// 「ルート」チップOFF時の完全非表示検証（MapView.layerOps.test.ts）向けにexport。
export const ROUTES_LAYER_ID = "route-candidates-line";
// 未選択候補の線は細く（2.5px）、走行中のスマホでは指で狙えない。見た目の線とは別に
// 透明な太い線を重ね、地図から候補を選べるようにする（DETAIL_HIT_LAYER_IDと同じ手法）。
export const ROUTES_HIT_LAYER_ID = "route-candidates-hit";
const OUTLINE_SOURCE_ID = "route-selected-outline";
export const OUTLINE_LAYER_ID = "route-selected-outline-line";
// 周回ルートの採用向き（順回り/逆回り）を示す矢印。8候補すべてに出すと輻輳するため専用
// sourceは持たず、選択中1候補のgeometryだけを保持するOUTLINE_SOURCE_IDをそのまま流用する
// （drawSelectedOutline参照）。
const ROUTE_ARROW_ICON_ID = "route-arrow-icon";
export const ROUTE_ARROW_HALO_LAYER_ID = "route-arrow-halo";
export const ROUTE_ARROW_LAYER_ID = "route-arrow";
const SPLICE_SOURCE_ID = "route-splice-stretches";
export const SPLICE_LAYER_ID = "route-splice-stretches-line";
// 帯そのもの（幅3〜5px）は指でタップできる太さではない。同じソースを参照する
// 当たり判定専用の太い・見えないレイヤー（DETAIL_HIT_LAYER_IDと同じ手法）。
// クリックはこちらだけへ登録する——両方へ登録すると1タップで2回発火し、
// 「同じ道をもう一度選ぶと元へ戻す」挙動と噛み合って何も起きなくなる。
export const SPLICE_HIT_LAYER_ID = "route-splice-stretches-hit";
// 編集中に「いま作っているルート」を描く線。元の候補線（寒色）の上へ、乗り換えと同じ暖色で
// 太く実線で重ねる——どこを通る道になったのかが、元との違いも含めて一目で分かるように。
const SPLICED_ROUTE_SOURCE_ID = "route-spliced-current";
export const SPLICED_ROUTE_LAYER_ID = "route-spliced-current-line";
const SPLICED_ROUTE_CASING_LAYER_ID = "route-spliced-current-casing";
export const SPLICED_ROUTE_WIDTH = 7;
export const DETAIL_SOURCE_ID = "route-detail-segments";
export const DETAIL_LAYER_ID = "route-detail-segments-line";
// DETAIL_LAYER_ID（見た目の線、幅6px）そのものはモバイルでタップしづらいため、同じ
// DETAIL_SOURCE_IDを参照する当たり判定専用の太い（幅24px）・見えない（line-opacity:0）
// レイヤー。クリックイベント・カーソル変更（interactiveLayerIds）はこちらへ登録し、見た目の
// 線幅・色は変えない（drawDetailSegments・buildInteractiveLayerIds参照）。
export const DETAIL_HIT_LAYER_ID = "route-detail-segments-hit";
// 色分け線・比較スロット線の下へ敷く縁取り。線の色はレンズ配色・スロット色で変わるため、
// 縁は線色にも背景にも依存しない一定の暗色にする。これが無いと、同系色の面レイヤー
// （災害・降水・標高図等）が背景に来たときに線の輪郭が消える。
const ROUTE_LINE_CASING_COLOR = "rgba(15, 23, 42, 0.8)";
export const DETAIL_CASING_LAYER_ID = "route-detail-segments-casing";
const SLOTS_CASING_LAYER_ID = "experiment-slots-casing";

const SLOTS_SOURCE_ID = "experiment-slots";
const SLOTS_LAYER_ID = "experiment-slots-line";

// routesToFeatureCollection/segmentsToFeatureCollection/computeRouteBoundsはexportして
// MapView.bench.ts（vitestのbench API）からGeoJSON構築のコストを直接計測できるようにしてある
// （ベンチマーク用途のみ。MapView自身は下のprivateなラッパー関数経由でしか呼ばない）。
export function routesToFeatureCollection(
  routes: RouteCandidate[],
  selectedRouteId: string | null,
  // trueのとき選択中候補をこのfeature collectionから除外する。選択中候補には
  // DETAIL_LAYER_ID（区間ごとの軸色分け線、drawDetailSegments）を重ね描きするため、
  // この不透明・単色（#2563eb、opacity 1、width 5）のROUTES_LAYER_IDを残すと下から
  // 透けて見える。DETAIL_LAYER_ID側は凡例で非表示にしたカテゴリをfilterで隠すが
  // この層は区間の絞り込みを持たないため、除外しないと「隠したはずの区間が単色の線として
  // 残って見える」。薄いハロー（drawSelectedOutline、opacity 0.25）は選択中候補を常時
  // 識別できるようにする別の意図的な表現のため、そちらは除外の対象にしない。
  excludeSelected = false,
): GeoJSON.FeatureCollection<GeoJSON.LineString, { selected: boolean; routeId: string }> {
  // 選択中の候補が他の線に隠れないよう、配列の最後（最前面）に描画されるようにする
  const ordered = [...routes]
    .filter((route) => !excludeSelected || route.id !== selectedRouteId)
    .sort((a, b) => Number(a.id === selectedRouteId) - Number(b.id === selectedRouteId));

  return {
    type: "FeatureCollection",
    features: ordered.map((route) => ({
      type: "Feature",
      // routeIdは地図から候補を選ぶための識別子（下記ROUTES_HIT_LAYER_IDのクリック）。
      properties: { selected: route.id === selectedRouteId, routeId: route.id },
      geometry: route.geometry,
    })),
  };
}

// 区間featureのproperties型。形状はfeature.geometry側に持たせるため、propertiesからは
// geometryを除外する（クリック時のポップアップ表示に必要な値だけを残す）。
export type RouteSegmentProperties = Omit<RouteSegmentDetail, "geometry">;

// RouteSegmentPropertiesのうちオブジェクト値を持つフィールド。MapLibreはGeoJSONソースの
// feature.propertiesをvector tile相当の内部表現へ変換する際、プリミティブ型
// （string/number/boolean）しか保持できないvector tile仕様の制約でオブジェクト値を
// JSON文字列へ自動的にシリアライズする。segmentsToFeatureCollectionが渡す時点では
// 素のオブジェクトだが、クリック時にqueryRenderedFeatures経由で読み戻すと文字列化されて
// いるため、handleRouteSegmentClickでここへ列挙した各フィールドをパースし直す。
// 新しいオブジェクト型フィールドを追加するときはこの配列へも追加すること
// （material_valuesの追加漏れで実際に実行時エラーが起きた）。
const ROUTE_SEGMENT_OBJECT_PROPERTY_KEYS = ["axis_difficulties", "axis_contributions", "material_values"] as const;

/** クリック時にqueryRenderedFeatures経由で読み戻したfeature.properties（ROUTE_SEGMENT_
 * OBJECT_PROPERTY_KEYS参照のとおりオブジェクト型フィールドが文字列化されている）を、
 * 元のオブジェクトへ復元する。文字列化されていなければそのまま返す。 */
export function restoreRouteSegmentProperties(raw: RouteSegmentProperties): RouteSegmentProperties {
  const restored = { ...raw };
  for (const key of ROUTE_SEGMENT_OBJECT_PROPERTY_KEYS) {
    const value = restored[key];
    if (typeof value === "string") {
      restored[key] = JSON.parse(value) as Record<string, number>;
    }
  }
  return restored;
}

export function segmentsToFeatureCollection(
  segments: RouteSegmentDetail[],
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

// MapView.routes.test.tsの「ルート」チップ表示切替テスト向けにexport。
// excludeSelectedはrouteToFeatureCollection側のdocコメント参照。
export function drawBaseRoutes(
  map: MapLibreMap,
  routes: RouteCandidate[],
  selectedRouteId: string | null,
  excludeSelected = false,
) {
  const data = routesToFeatureCollection(routes, selectedRouteId, excludeSelected);

  const applyData = () => {
    const source = map.getSource(ROUTES_SOURCE_ID) as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    } else {
      map.addSource(ROUTES_SOURCE_ID, { type: "geojson", data });
      map.addLayer({
        id: ROUTES_LAYER_ID,
        type: "line",
        source: ROUTES_SOURCE_ID,
        paint: {
          // 未選択の候補は「背景の参考線」として見えればよく、選択中候補
          // （特にroute-detail-segments-lineの路面/難易度色分け）を主役として引き立てる
          // 脇役にする。色はOpenFreeMapベースマップの主要道路（暖色系のオレンジ〜ベージュ）に
          // 溶け込まない、ベースマップに存在しない寒色（スレート）を使う。8候補比較
          // （地図上での見比べ）自体は維持したいため、不透明度0.45程度まで下げると
          // 背景に埋没して見えなくなる一方、選択中候補ほど目立たせたくもないため、
          // その中間の「はっきり見えるが選択中候補ほどは目立たない」不透明度に調整している。
          "line-color": ["case", ["get", "selected"], "#2563eb", "#64748b"],
          "line-width": ["case", ["get", "selected"], 5, 2.5],
          "line-opacity": ["case", ["get", "selected"], 1, 0.65],
        },
      });
      map.addLayer({
        id: ROUTES_HIT_LAYER_ID,
        type: "line",
        source: ROUTES_SOURCE_ID,
        paint: { "line-width": 18, "line-opacity": 0 },
      });
    }
    // 「ルート」チップOFFで隠した後、再度ONにしたときに再表示されるよう、
    // 更新のたびにvisibility="visible"を明示する（addLayer直後は既定でvisibleだが、
    // hideBaseRoutesでnoneにした後の再表示はこの明示が無いと戻らない）。
    setLayerVisibility(map, ROUTES_LAYER_ID, true);
    setLayerVisibility(map, ROUTES_HIT_LAYER_ID, true);
  };

  runWhenStyleReady(map, applyData);
}

// 候補線（寒色）と競合しない暖色。選んでいない区間は破線で「乗り換えられる」ことだけを
// 示し、選んだ区間は実線・太めにする。式はexportして`MapView.splice.test.ts`が
// style-specの評価器で検証する（実機はmaplibre-gl内蔵の同パッケージで評価するため、
// テストが通る式が実機で別の意味になりうる版ずれを
// docs/architecture/tech-stack.mdが禁じている）。
export const SPLICE_COLOR = "#c2612b";
// 当たり判定の太さ。ルート区間の当たり判定（DETAIL_HIT_LAYER_ID）と同じにする——
// 指の接地面はどの線を触るかで変わらない。
export const SPLICE_HIT_WIDTH = 24;
export const SPLICE_WIDTH_EXPRESSION: unknown[] = ["case", ["get", "taken"], 5, 3];
export const SPLICE_OPACITY_EXPRESSION: unknown[] = ["case", ["get", "taken"], 1, 0.75];
export const SPLICE_DASH_EXPRESSION: unknown[] = ["case", ["get", "taken"], ["literal", [1, 0]], ["literal", [2, 1.5]]];

/** 乗り換えられる区間1本ぶんの描画情報。`taken`は相手の道を選んでいる状態。 */
export interface SpliceStretchFeature {
  index: number;
  taken: boolean;
  coordinates: GeoJSON.Position[];
}

export function spliceStretchesToFeatureCollection(
  stretches: SpliceStretchFeature[],
): GeoJSON.FeatureCollection<GeoJSON.LineString, { index: number; taken: boolean }> {
  return {
    type: "FeatureCollection",
    // 選んだ区間が未選択の帯に隠れないよう、配列の最後（最前面）へ回す
    features: [...stretches]
      .sort((a, b) => Number(a.taken) - Number(b.taken))
      .map((stretch) => ({
        type: "Feature" as const,
        properties: { index: stretch.index, taken: stretch.taken },
        geometry: { type: "LineString" as const, coordinates: stretch.coordinates },
      })),
  };
}

/** 比較相手が別の道を通る区間を帯で描く。
 *
 * 選んでいない区間は破線で「乗り換えられる」ことだけを示し、選んだ区間は実線にする。
 * 候補線より上へ置く——下に敷くと、差し替えた先が元の経路に隠れて変化が見えない。 */
export function drawSpliceStretches(map: MapLibreMap, stretches: SpliceStretchFeature[]) {
  const data = spliceStretchesToFeatureCollection(stretches);

  const applyData = () => {
    const source = map.getSource(SPLICE_SOURCE_ID) as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    } else {
      map.addSource(SPLICE_SOURCE_ID, { type: "geojson", data });
      map.addLayer({
        id: SPLICE_LAYER_ID,
        type: "line",
        source: SPLICE_SOURCE_ID,
        paint: {
          // 候補線（寒色）と競合しない暖色。選んだ区間だけを主役にする。
          "line-color": SPLICE_COLOR,
          /* eslint-disable @typescript-eslint/no-explicit-any */
          "line-width": SPLICE_WIDTH_EXPRESSION as any,
          "line-opacity": SPLICE_OPACITY_EXPRESSION as any,
          "line-dasharray": SPLICE_DASH_EXPRESSION as any,
          /* eslint-enable @typescript-eslint/no-explicit-any */
        },
      });
      map.addLayer({
        id: SPLICE_HIT_LAYER_ID,
        type: "line",
        source: SPLICE_SOURCE_ID,
        paint: { "line-width": SPLICE_HIT_WIDTH, "line-opacity": 0 },
      });
    }
    setLayerVisibility(map, SPLICE_LAYER_ID, true);
    setLayerVisibility(map, SPLICE_HIT_LAYER_ID, true);
  };

  runWhenStyleReady(map, applyData);
}

/** 編集中の「いま作っているルート」を描く（帯より上、候補線より上）。 */
export function drawSplicedRoute(map: MapLibreMap, coordinates: readonly GeoJSON.Position[]) {
  const data: GeoJSON.FeatureCollection<GeoJSON.LineString> = {
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [...coordinates] } }],
  };

  runWhenStyleReady(map, () => {
    const source = map.getSource(SPLICED_ROUTE_SOURCE_ID) as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    } else {
      map.addSource(SPLICED_ROUTE_SOURCE_ID, { type: "geojson", data });
      // 縁取りを先に敷く。面レイヤー（災害・降水等）の上でも輪郭が消えないようにする。
      map.addLayer({
        id: SPLICED_ROUTE_CASING_LAYER_ID,
        type: "line",
        source: SPLICED_ROUTE_SOURCE_ID,
        paint: { "line-color": ROUTE_LINE_CASING_COLOR, "line-width": SPLICED_ROUTE_WIDTH + 4 },
        layout: { "line-cap": "round", "line-join": "round" },
      });
      map.addLayer({
        id: SPLICED_ROUTE_LAYER_ID,
        type: "line",
        source: SPLICED_ROUTE_SOURCE_ID,
        paint: { "line-color": SPLICE_COLOR, "line-width": SPLICED_ROUTE_WIDTH },
        layout: { "line-cap": "round", "line-join": "round" },
      });
    }
    setLayerVisibility(map, SPLICED_ROUTE_CASING_LAYER_ID, true);
    setLayerVisibility(map, SPLICED_ROUTE_LAYER_ID, true);
  });
}

export function hideSplicedRoute(map: MapLibreMap) {
  runWhenStyleReady(map, () => {
    setLayerVisibility(map, SPLICED_ROUTE_CASING_LAYER_ID, false);
    setLayerVisibility(map, SPLICED_ROUTE_LAYER_ID, false);
  });
}

export function hideSpliceStretches(map: MapLibreMap) {
  runWhenStyleReady(map, () => {
    setLayerVisibility(map, SPLICE_LAYER_ID, false);
    setLayerVisibility(map, SPLICE_HIT_LAYER_ID, false);
  });
}

export function hideBaseRoutes(map: MapLibreMap) {
  runWhenStyleReady(map, () => {
    setLayerVisibility(map, ROUTES_LAYER_ID, false);
    setLayerVisibility(map, ROUTES_HIT_LAYER_ID, false);
  });
}

// 選択中候補を常時識別できるよう、色分けレイヤーの下に薄いハローを敷く
export function drawSelectedOutline(map: MapLibreMap, routes: RouteCandidate[], selectedRouteId: string | null) {
  const selected = routes.find((r) => r.id === selectedRouteId);
  const data: GeoJSON.FeatureCollection<GeoJSON.LineString> = {
    type: "FeatureCollection",
    features: selected ? [{ type: "Feature", properties: {}, geometry: selected.geometry }] : [],
  };

  const applyData = () => {
    const source = map.getSource(OUTLINE_SOURCE_ID) as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    } else {
      map.addSource(OUTLINE_SOURCE_ID, { type: "geojson", data });
      map.addLayer(
        {
          id: OUTLINE_LAYER_ID,
          type: "line",
          source: OUTLINE_SOURCE_ID,
          paint: { "line-color": "#1e3a8a", "line-width": 10, "line-opacity": 0.25 },
        },
        map.getLayer(ROUTES_LAYER_ID) ? ROUTES_LAYER_ID : undefined,
      );
      ensureRouteArrowLayer(map);
    }
    // hideSelectedOutlineでnoneにした後の再表示のため明示する
    // （drawBaseRoutesと同じ理由）。矢印レイヤーもハロー・線と同じ表示状態に揃える。
    setLayerVisibility(map, OUTLINE_LAYER_ID, true);
    setLayerVisibility(map, ROUTE_ARROW_HALO_LAYER_ID, true);
    setLayerVisibility(map, ROUTE_ARROW_LAYER_ID, true);
  };

  runWhenStyleReady(map, applyData);
}

export function hideSelectedOutline(map: MapLibreMap) {
  runWhenStyleReady(map, () => {
    setLayerVisibility(map, OUTLINE_LAYER_ID, false);
    setLayerVisibility(map, ROUTE_ARROW_HALO_LAYER_ID, false);
    setLayerVisibility(map, ROUTE_ARROW_LAYER_ID, false);
  });
}

// 「ルート」チップ（routeLayerOn）に応じて候補線・選択中候補のハロー/矢印をまとめて
// 出し分ける共通処理。呼び出し元effect2箇所とredrawAllLayers（スタイル再構築時の再描画）の
// 計3箇所が個別にif(routeLayerOn){draw...}else{hide...}を書くと、呼び出し元が増えるたびに
// routeLayerOnの判定漏れ（「ルート」チップOFFで隠した候補線・ハロー・矢印が地図データの
// 再読み込み時に復活する等）が起きやすいため、1箇所へ集約する。
export function applyRouteLayerVisibility(
  map: MapLibreMap,
  routeLayerOn: boolean,
  routes: RouteCandidate[],
  selectedRouteId: string | null,
  // 選択中候補にDETAIL_LAYER_ID（区間ごとの軸色分け線）を重ね描きする場合はtrue。
  // routesToFeatureCollectionのexcludeSelectedへそのまま渡し、単色のROUTES_LAYER_IDが
  // 色分け線の下から透けて見えるのを防ぐ。
  hasDetailSegments = false,
) {
  if (routeLayerOn) {
    drawBaseRoutes(map, routes, selectedRouteId, hasDetailSegments);
    drawSelectedOutline(map, routes, selectedRouteId);
  } else {
    hideBaseRoutes(map);
    hideSelectedOutline(map);
  }
}

// 周回ルートの採用向き（順回り/逆回り）を矢印で明示する。
// symbol-placement: "line" + icon-rotation-alignment: "map"の組み合わせだけで、LineStringの
// 座標順（逆回り候補は座標を逆順に構築済みで、RouteCandidate.geometry/segmentsは採用された
// 向きの座標順で返る）がそのまま矢印の向きに反映されるため、フロント側で「どちらが
// 採用されたか」を判定する追加ロジックは不要。
// ハロー（縁取り）層+主層の2層重ねで、衝突判定は無効化する（icon-allow-overlap /
// icon-ignore-placement: true）。MapLibreはレイヤーの上から順にシンボルを配置するため、
// 衝突判定を有効にしたまま2層重ねると、先に配置された主層（上）と同位置・大きめの
// ハロー層（下）が「衝突」として全て落ちる（風の矢印はこの構造の不具合を踏まえ
// icon-halo-*で1層にまとめている、ensureDynamicWeatherLayer参照）。ルート矢印は
// 選択中候補の線上だけに出る小さなシンボルのため、basemapのラベルと重なる不利益より
// 「必ず縁取り付きで一定間隔に出る」ことを優先し、衝突判定の無効化で対応する。
export function ensureRouteArrowLayer(map: MapLibreMap) {
  if (map.getLayer(ROUTE_ARROW_LAYER_ID)) return;
  if (!map.hasImage(ROUTE_ARROW_ICON_ID)) {
    map.addImage(ROUTE_ARROW_ICON_ID, createRouteArrowIcon(), { sdf: true });
  }
  const lineLayout = {
    "icon-image": ROUTE_ARROW_ICON_ID,
    "symbol-placement": "line",
    "symbol-spacing": ROUTE_ARROW_SPACING_PX,
    "icon-rotation-alignment": "map",
    "icon-allow-overlap": true,
    "icon-ignore-placement": true,
  } as const;
  map.addLayer({
    id: ROUTE_ARROW_HALO_LAYER_ID,
    type: "symbol",
    source: OUTLINE_SOURCE_ID,
    layout: {
      ...lineLayout,
      "icon-size": zoomIconSizeExpression(ROUTE_ARROW_BASE_SCALE * ROUTE_ARROW_HALO_SCALE_MULTIPLIER),
    },
    // 縁取りは濃色、矢印本体は白。区間色分け線はモードにより紺・緑・赤・紫と変わるため、
    // 線と同系になりうる有彩色ではなく、どの線色の上でも浮く白を本体に使い、濃色の縁取りで
    // 線・basemapの双方から切り離す（ナビアプリの経路上シェブロンと同じ配色）。
    paint: { "icon-color": "#111827", "icon-opacity": 0.95 },
  });
  map.addLayer({
    id: ROUTE_ARROW_LAYER_ID,
    type: "symbol",
    source: OUTLINE_SOURCE_ID,
    layout: { ...lineLayout, "icon-size": zoomIconSizeExpression(ROUTE_ARROW_BASE_SCALE) },
    paint: { "icon-color": "#ffffff", "icon-opacity": 1 },
  });
  keepRouteArrowsAboveDetailSegments(map);
}

// 矢印は選択中候補の区間色分け線（DETAIL_LAYER_ID、幅6px・不透明）と
// その当たり判定線（DETAIL_HIT_LAYER_ID）より上に描く。矢印層はページ表示直後
// （routes=[]でのdrawSelectedOutline）に、区間色分け線は最初の生成後に作られるため、
// 作成順に任せると常に矢印が下になり線に隠れる。どちらが先に作られても
// 「色分け線 → 当たり判定線 → 矢印ハロー → 矢印」の順になるよう、矢印層の作成時は
// ここで既存の色分け線を矢印の直下へ移し、色分け線の作成時（drawDetailSegments）は
// 矢印ハローをbeforeIdに指定する。
export function keepRouteArrowsAboveDetailSegments(map: MapLibreMap) {
  if (!map.getLayer(ROUTE_ARROW_HALO_LAYER_ID)) return;
  for (const layerId of [DETAIL_CASING_LAYER_ID, DETAIL_LAYER_ID, DETAIL_HIT_LAYER_ID]) {
    if (map.getLayer(layerId)) map.moveLayer(layerId, ROUTE_ARROW_HALO_LAYER_ID);
  }
}

// 実験スロット（研究インターフェース改善 §10-3）の重ね描き。各スロットの代表候補
// （topCandidate、生成直後のoverall_difficulty最小で固定）の全体形状をスロット別の色で描く
// （「路面重視にしたら形が変わったか」等の比較が本命）。detail-segments（現在選択中の
// 色分け表示）より下・base routes（8候補の参考線）より上に置くため、作成時にDETAIL_LAYER_IDの
// 直下（既に存在すれば）を明示指定する（drawSelectedOutlineと同じ考え方）。
export function drawExperimentSlots(map: MapLibreMap, slots: ExperimentSlot[]) {
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
    // 色分け線と同じ理由の縁取り（スロット色は緑・橙・紫で、緑は面レイヤーに埋もれる）。
    map.addLayer(
      {
        id: SLOTS_CASING_LAYER_ID,
        type: "line",
        source: SLOTS_SOURCE_ID,
        paint: { "line-color": ROUTE_LINE_CASING_COLOR, "line-width": 7, "line-opacity": 0.85 },
      },
      map.getLayer(DETAIL_CASING_LAYER_ID)
        ? DETAIL_CASING_LAYER_ID
        : map.getLayer(DETAIL_LAYER_ID)
          ? DETAIL_LAYER_ID
          : undefined,
    );
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
      map.getLayer(DETAIL_CASING_LAYER_ID)
        ? DETAIL_CASING_LAYER_ID
        : map.getLayer(DETAIL_LAYER_ID)
          ? DETAIL_LAYER_ID
          : undefined,
    );
  };

  runWhenStyleReady(map, applyData);
}

// ルートレイヤー（有向・選択中ルート基準のデータ。風・勾配）は、選択中候補にのみ
// 動的に重ね描きする。色分けモード・凡例フィルタの切替はスタイル式の差し替えのみ。
export function drawDetailSegments(
  map: MapLibreMap,
  segments: RouteSegmentDetail[],
  mode: RouteStyleMode,
  hiddenLegendKeys: readonly string[],
) {
  const data = segmentsToFeatureCollection(segments);

  const applyData = () => {
    const source = map.getSource(DETAIL_SOURCE_ID) as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    } else {
      map.addSource(DETAIL_SOURCE_ID, { type: "geojson", data });
      // 進行方向矢印（ROUTE_ARROW_HALO_LAYER_ID/ROUTE_ARROW_LAYER_ID）より
      // 下に置く（keepRouteArrowsAboveDetailSegments参照）。
      const beforeId = map.getLayer(ROUTE_ARROW_HALO_LAYER_ID) ? ROUTE_ARROW_HALO_LAYER_ID : undefined;
      // 縁取りを先に追加して色分け線の下へ置く（同じbeforeIdなら先に追加した方が下になる）。
      map.addLayer(
        {
          id: DETAIL_CASING_LAYER_ID,
          type: "line",
          source: DETAIL_SOURCE_ID,
          paint: { "line-color": ROUTE_LINE_CASING_COLOR, "line-width": 10, "line-opacity": 1 },
        },
        beforeId,
      );
      map.addLayer(
        {
          id: DETAIL_LAYER_ID,
          type: "line",
          source: DETAIL_SOURCE_ID,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          paint: { "line-color": mode.colorExpression as any, "line-width": 6, "line-opacity": 1 },
        },
        beforeId,
      );
      // 当たり判定専用の見えない太い線（DETAIL_HIT_LAYER_IDのdocstring参照）。
      // 同じソース・同じfilterを共有し、見た目の線（DETAIL_LAYER_ID）の上に重ねる
      // （line-opacity:0のため描画順自体は見た目に影響しない）。
      map.addLayer(
        {
          id: DETAIL_HIT_LAYER_ID,
          type: "line",
          source: DETAIL_SOURCE_ID,
          paint: { "line-width": 24, "line-opacity": 0 },
        },
        beforeId,
      );
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.setPaintProperty(DETAIL_LAYER_ID, "line-color", mode.colorExpression as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const filterExpression = buildLegendFilterExpression(mode.legend, hiddenLegendKeys) as any;
    map.setFilter(DETAIL_LAYER_ID, filterExpression);
    // 縁取り・当たり判定レイヤーも同じfilterを適用する（非表示カテゴリの区間は見た目どおり
    // 縁だけ残らず、クリックもできないようにする）。
    map.setFilter(DETAIL_CASING_LAYER_ID, filterExpression);
    map.setFilter(DETAIL_HIT_LAYER_ID, filterExpression);
    setLayerVisibility(map, DETAIL_CASING_LAYER_ID, true);
    setLayerVisibility(map, DETAIL_LAYER_ID, true);
    setLayerVisibility(map, DETAIL_HIT_LAYER_ID, true);
  };

  runWhenStyleReady(map, applyData);
}

export function hideDetailSegments(map: MapLibreMap) {
  runWhenStyleReady(map, () => {
    setLayerVisibility(map, DETAIL_CASING_LAYER_ID, false);
    setLayerVisibility(map, DETAIL_LAYER_ID, false);
    setLayerVisibility(map, DETAIL_HIT_LAYER_ID, false);
  });
}

// ルート矢印のsymbol-spacing（線に沿った矢印間隔、画面px単位。ズームで密度が
// 自動調整されるためズーム別の値は持たない）・基準サイズ。
const ROUTE_ARROW_SPACING_PX = 80;
// 区間色分け線（幅6px）の上に載せても読める大きさにする。
const ROUTE_ARROW_BASE_SCALE = 0.8;
// ハロー層は主層より一回り大きい濃色シルエットを下に敷く倍率（風の矢印のWIND_ICON_HALO_
// SCALE_MULTIPLIERと同じ考え方）。
const ROUTE_ARROW_HALO_SCALE_MULTIPLIER = 1.5;

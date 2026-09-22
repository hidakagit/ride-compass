/** ルート（候補の参考線・選択中候補・区間の色分け・乗り換えの帯・合成ルート・
 * 比較スロット・進行方向の矢印）。
 *
 * **重なりはこのファイルの宣言の並びだけが決める**（背面→前面）。押したときに拾う対象は
 * 見た目の線とは別の透明な線が持つ——見た目の太さと、指で押せる幅を別々に決めるため。
 */
import type { ExpressionSpecification, FilterSpecification } from "maplibre-gl";
import type { Feature, FeatureCollection, LineString } from "geojson";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";
import { zoomScaleExpression } from "../sceneBuilders";

/** [経度, 緯度] の並び。 */
export type RoutePoint = readonly [number, number];
export type RoutePath = readonly RoutePoint[];

// 見た目の値。基礎地図の主要道路（暖色系）に溶け込まない寒色を参考線に、
// 乗り換えと合成には候補線と競合しない暖色を使う。
const CANDIDATE_COLOR = "#64748b";
const CANDIDATE_WIDTH_PX = 2.5;
const SELECTED_HALO_COLOR = "#1e3a8a";
const SELECTED_HALO_WIDTH_PX = 10;
const SELECTED_HALO_OPACITY = 0.25;
/** 縁取りは線の色にも背景にも依存しない一定の暗色——線と同系色の面が背景に来ても
 * 輪郭が残るようにする。 */
const CASING_COLOR = "rgba(15, 23, 42, 0.8)";
const SPLICE_COLOR = "#c2612b";
const SPLICE_WIDTH_PX = 3;
const SPLICE_SELECTED_WIDTH_PX = 5;
const SPLICE_OPACITY = 0.85;
const SPLICE_DASH: readonly number[] = [2, 1.5];
const COMPOSITE_WIDTH_PX = 7;
const COMPOSITE_CASING_WIDTH_PX = 11;
const SLOT_WIDTH_PX = 4;
const SLOT_CASING_WIDTH_PX = 7;
const DETAIL_CASING_WIDTH_PX = 10;
const DETAIL_WIDTH_PX = 6;
/** 指の接地面。見た目の線がどれだけ細くても押せる幅にする。 */
const HIT_WIDTH_PX = 24;
const CANDIDATE_HIT_WIDTH_PX = 18;
/** 矢印は本体を白・縁を濃色にする——区間の色分けはレンズのモードで変わるため、
 * 線と同系色になりうる有彩色を本体に使わない。 */
const ARROW_COLOR = "#ffffff";
const ARROW_HALO_COLOR = "#111827";
const ARROW_SPACING_PX = 80;
const ARROW_HALO_SCALE = 1.5;
/** 大きさはズームに追従させる——固定ピクセルだと、拡大するほど周囲の道路だけが太くなる。 */
const ARROW_SIZE_BY_ZOOM: readonly (readonly [number, number])[] = [
  [10, 0.6],
  [13, 0.8],
  [16, 1.2],
  [19, 1.6],
];

const HIT_PAINT = { "line-color": "#000000", "line-opacity": 0 } as const;
const ROUND_CAP = { "line-cap": "round", "line-join": "round" } as const;

export const ROUTE_HIT_TARGET = "route";
export const ROUTE_HIT_TARGET_CANDIDATE = "routeCandidate";
export const ROUTE_HIT_TARGET_SEGMENT = "routeSegment";
export const ROUTE_HIT_TARGET_SPLICE_BAND = "routeSpliceBand";

const ROUTE_ID_PROPERTY = "routeId";
const SPLICE_SELECTED_PROPERTY = "spliceSelected";
const SLOT_COLOR_PROPERTY = "slotColor";

type Shape = { readonly path: RoutePath; readonly properties?: Readonly<Record<string, unknown>> };

export type RouteState = {
  readonly visible: boolean;
  readonly candidates: readonly { readonly routeId: string; readonly path: RoutePath }[];
  readonly selectedRouteId: string | null;
  readonly segments: readonly Shape[];
  /** 区間の色。段の切り方・配色は軸カタログが決めるため、出来上がった式のまま受け取る。 */
  readonly segmentColor: string | ExpressionSpecification;
  /** 凡例で隠した段を落とす絞り込み。色分け線・縁取り・当たり判定の3枚へ同じものを当てる。 */
  readonly hiddenBandFilter?: FilterSpecification;
  readonly spliceBands: readonly (Shape & { readonly selected: boolean })[];
  readonly composite: Shape | null;
  readonly comparisonSlots: readonly { readonly path: RoutePath; readonly color: string }[];
  /** 進行方向の矢印の絵。色を持たないシルエット（SDF）であること——色はレイヤーが決める。 */
  readonly arrowIconImage: string | null;
};

const SOURCE = {
  candidates: "route-candidates",
  selected: "route-selected",
  segments: "route-segments",
  spliceBands: "route-splice-bands",
  composite: "route-composite",
  slots: "route-slots",
} as const;

function line(path: RoutePath, properties: Readonly<Record<string, unknown>> = {}): Feature<LineString> {
  return {
    type: "Feature",
    geometry: { type: "LineString", coordinates: path.map(([lng, lat]) => [lng, lat]) },
    properties: { ...properties },
  };
}

function collection(features: readonly Feature<LineString>[]): FeatureCollection<LineString> {
  return { type: "FeatureCollection", features: [...features] };
}

function arrowSize(scale: number): unknown {
  return zoomScaleExpression(scale, ARROW_SIZE_BY_ZOOM);
}

export const routeGroup = declareGroup<RouteState>("route", (state) => {
  const selected = state.candidates.find((candidate) => candidate.routeId === state.selectedRouteId) ?? null;
  // 区間を描いている候補は参考線から外す——同じ線を2本重ねると、上の色分け線の下から
  // 単色の線がはみ出す。
  const detailed = state.segments.length > 0 ? selected : null;
  const references = state.candidates.filter((candidate) => candidate !== detailed);
  const bands = (selectedBand: boolean) => state.spliceBands.filter((band) => band.selected === selectedBand);

  const sources: readonly SceneSourceEntry[] = [
    { id: SOURCE.candidates, spec: { type: "geojson" }, data: collection(references.map((c) => line(c.path, { [ROUTE_ID_PROPERTY]: c.routeId }))) },
    { id: SOURCE.selected, spec: { type: "geojson" }, data: collection(selected === null ? [] : [line(selected.path)]) },
    { id: SOURCE.segments, spec: { type: "geojson" }, data: collection(state.segments.map((s) => line(s.path, s.properties))) },
    {
      id: SOURCE.spliceBands,
      spec: { type: "geojson" },
      data: collection(state.spliceBands.map((b) => line(b.path, { ...b.properties, [SPLICE_SELECTED_PROPERTY]: b.selected }))),
    },
    { id: SOURCE.composite, spec: { type: "geojson" }, data: collection(state.composite === null ? [] : [line(state.composite.path, state.composite.properties)]) },
    { id: SOURCE.slots, spec: { type: "geojson" }, data: collection(state.comparisonSlots.map((s) => line(s.path, { [SLOT_COLOR_PROPERTY]: s.color }))) },
  ];

  const banded = (role: string, selectedBand: boolean): SceneLayerEntry => ({
    role,
    tier: "route",
    source: SOURCE.spliceBands,
    type: "line",
    paint: {
      "line-color": SPLICE_COLOR,
      "line-width": selectedBand ? SPLICE_SELECTED_WIDTH_PX : SPLICE_WIDTH_PX,
      "line-opacity": SPLICE_OPACITY,
      ...(selectedBand ? {} : { "line-dasharray": [...SPLICE_DASH] }),
    },
    visible: state.visible && bands(selectedBand).length > 0,
    filter: ["==", ["get", SPLICE_SELECTED_PROPERTY], selectedBand] as unknown as FilterSpecification,
  });

  const withBandFilter = (entry: SceneLayerEntry): SceneLayerEntry =>
    state.hiddenBandFilter === undefined ? entry : { ...entry, filter: state.hiddenBandFilter };

  // 背面から前面。
  const layers: readonly SceneLayerEntry[] = [
    { role: "selectedHalo", tier: "route", source: SOURCE.selected, type: "line", visible: state.visible, paint: { "line-color": SELECTED_HALO_COLOR, "line-width": SELECTED_HALO_WIDTH_PX, "line-opacity": SELECTED_HALO_OPACITY } },
    { role: "candidateLine", tier: "route", source: SOURCE.candidates, type: "line", visible: state.visible, paint: { "line-color": CANDIDATE_COLOR, "line-width": CANDIDATE_WIDTH_PX, "line-opacity": 0.65 } },
    { role: "candidateHit", tier: "route", source: SOURCE.candidates, type: "line", visible: state.visible, paint: { ...HIT_PAINT, "line-width": CANDIDATE_HIT_WIDTH_PX }, hitTargets: [ROUTE_HIT_TARGET, ROUTE_HIT_TARGET_CANDIDATE] },
    { role: "slotCasing", tier: "route", source: SOURCE.slots, type: "line", visible: state.visible, paint: { "line-color": CASING_COLOR, "line-width": SLOT_CASING_WIDTH_PX, "line-opacity": 0.85 } },
    { role: "slotLine", tier: "route", source: SOURCE.slots, type: "line", visible: state.visible, paint: { "line-color": ["get", SLOT_COLOR_PROPERTY], "line-width": SLOT_WIDTH_PX, "line-opacity": 0.85 } },
    banded("spliceBandLine", false),
    banded("spliceBandSelectedLine", true),
    { role: "compositeCasing", tier: "route", source: SOURCE.composite, type: "line", visible: state.visible, layout: ROUND_CAP, paint: { "line-color": CASING_COLOR, "line-width": COMPOSITE_CASING_WIDTH_PX } },
    { role: "compositeLine", tier: "route", source: SOURCE.composite, type: "line", visible: state.visible, layout: ROUND_CAP, paint: { "line-color": SPLICE_COLOR, "line-width": COMPOSITE_WIDTH_PX } },
    withBandFilter({ role: "detailCasing", tier: "route", source: SOURCE.segments, type: "line", visible: state.visible, paint: { "line-color": CASING_COLOR, "line-width": DETAIL_CASING_WIDTH_PX } }),
    withBandFilter({ role: "detailLine", tier: "route", source: SOURCE.segments, type: "line", visible: state.visible, paint: { "line-color": state.segmentColor, "line-width": DETAIL_WIDTH_PX } }),
    withBandFilter({
      role: "detailHit",
      tier: "route",
      source: SOURCE.segments,
      type: "line",
      visible: state.visible,
      paint: { ...HIT_PAINT, "line-width": HIT_WIDTH_PX },
      hitTargets: [ROUTE_HIT_TARGET, ROUTE_HIT_TARGET_SEGMENT],
    }),
    // 帯の当たり判定は区間の当たり判定より前面——区間の当たり判定はルート全体を覆うため、
    // 後ろだと帯を一度も押せない。
    { role: "spliceBandHit", tier: "route", source: SOURCE.spliceBands, type: "line", visible: state.visible, paint: { ...HIT_PAINT, "line-width": HIT_WIDTH_PX }, hitTargets: [ROUTE_HIT_TARGET, ROUTE_HIT_TARGET_SPLICE_BAND] },
    ...(state.arrowIconImage === null
      ? []
      : [
          // 衝突判定を無効にする——有効にすると、同じ位置の2層のうち後ろが丸ごと落ちる。
          { role: "arrowHalo", tier: "route" as const, source: SOURCE.selected, type: "symbol" as const, visible: state.visible, layout: { "icon-image": state.arrowIconImage, "symbol-placement": "line", "symbol-spacing": ARROW_SPACING_PX, "icon-allow-overlap": true, "icon-ignore-placement": true, "icon-size": arrowSize(ARROW_HALO_SCALE) }, paint: { "icon-color": ARROW_HALO_COLOR, "icon-opacity": 0.95 } },
          { role: "arrow", tier: "route" as const, source: SOURCE.selected, type: "symbol" as const, visible: state.visible, layout: { "icon-image": state.arrowIconImage, "symbol-placement": "line", "symbol-spacing": ARROW_SPACING_PX, "icon-allow-overlap": true, "icon-ignore-placement": true, "icon-size": arrowSize(1) }, paint: { "icon-color": ARROW_COLOR, "icon-opacity": 1 } },
        ]),
  ];

  return { sources, layers };
});

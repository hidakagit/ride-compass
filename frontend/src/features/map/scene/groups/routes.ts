/** ルート（候補の参考線・選択中候補・区間の色分け・乗り換えの帯・合成ルート・
 * 比較スロット・進行方向の矢印）。
 *
 * **重なりはこのファイルの宣言の並びだけが決める**（背面→前面）。押したときに拾う対象は
 * 見た目の線とは別の透明な線が持つ——見た目の太さと、指で押せる幅を別々に決めるため。
 */
import { mapDisplay } from "@/types/generated/mapDisplay";
import palette from "@/types/generated/palette.json";
import type { ExpressionSpecification, FilterSpecification } from "maplibre-gl";
import type { Feature, FeatureCollection, LineString } from "geojson";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";
import { zoomScaleExpression } from "../sceneBuilders";

/** [経度, 緯度] の並び。 */
type RoutePoint = readonly [number, number];
export type RoutePath = readonly RoutePoint[];

/** 見た目の値は源泉が配る（`backend/app/domain/map_display.py`）。ここは受け取って塗るだけ。 */
const ROUTE = mapDisplay.route;

/** 指の接地面。**見た目の線がどれだけ細くても押せる幅にする**ので、線の太さからは導けない
 * ——媒体（指の大きさ）が決める値で、配信側は知らない。 */
const HIT_WIDTH_PX = 24;
const CANDIDATE_HIT_WIDTH_PX = 18;

const HIT_PAINT = { "line-color": palette.semantic.hit, "line-opacity": 0 } as const;
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
  return zoomScaleExpression(scale, ROUTE.arrowSizeByZoom);
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
      "line-color": palette.semantic.route_splice,
      "line-width": selectedBand ? ROUTE.lineWidthsPx.spliceSelected : ROUTE.lineWidthsPx.splice,
      "line-opacity": ROUTE.opacities.splice,
      ...(selectedBand ? {} : { "line-dasharray": [...ROUTE.spliceDash] }),
    },
    visible: state.visible && bands(selectedBand).length > 0,
    filter: ["==", ["get", SPLICE_SELECTED_PROPERTY], selectedBand] as unknown as FilterSpecification,
  });

  const withBandFilter = (entry: SceneLayerEntry): SceneLayerEntry =>
    state.hiddenBandFilter === undefined ? entry : { ...entry, filter: state.hiddenBandFilter };

  // 背面から前面。
  const layers: readonly SceneLayerEntry[] = [
    { role: "selectedHalo", tier: "route", source: SOURCE.selected, type: "line", visible: state.visible, paint: { "line-color": palette.semantic.route_selected_halo, "line-width": ROUTE.lineWidthsPx.selectedHalo, "line-opacity": ROUTE.opacities.selectedHalo } },
    { role: "candidateLine", tier: "route", source: SOURCE.candidates, type: "line", visible: state.visible, paint: { "line-color": palette.semantic.route_candidate, "line-width": ROUTE.lineWidthsPx.candidate, "line-opacity": 0.65 } },
    { role: "candidateHit", tier: "route", source: SOURCE.candidates, type: "line", visible: state.visible, paint: { ...HIT_PAINT, "line-width": CANDIDATE_HIT_WIDTH_PX }, hitTargets: [ROUTE_HIT_TARGET, ROUTE_HIT_TARGET_CANDIDATE] },
    { role: "slotCasing", tier: "route", source: SOURCE.slots, type: "line", visible: state.visible, paint: { "line-color": palette.semantic.route_casing, "line-width": ROUTE.casingWidthsPx.slot, "line-opacity": 0.85 } },
    { role: "slotLine", tier: "route", source: SOURCE.slots, type: "line", visible: state.visible, paint: { "line-color": ["get", SLOT_COLOR_PROPERTY], "line-width": ROUTE.lineWidthsPx.slot, "line-opacity": 0.85 } },
    banded("spliceBandLine", false),
    banded("spliceBandSelectedLine", true),
    { role: "compositeCasing", tier: "route", source: SOURCE.composite, type: "line", visible: state.visible, layout: ROUND_CAP, paint: { "line-color": palette.semantic.route_casing, "line-width": ROUTE.casingWidthsPx.composite } },
    { role: "compositeLine", tier: "route", source: SOURCE.composite, type: "line", visible: state.visible, layout: ROUND_CAP, paint: { "line-color": palette.semantic.route_splice, "line-width": ROUTE.lineWidthsPx.composite } },
    withBandFilter({ role: "detailCasing", tier: "route", source: SOURCE.segments, type: "line", visible: state.visible, paint: { "line-color": palette.semantic.route_casing, "line-width": ROUTE.casingWidthsPx.detail } }),
    withBandFilter({ role: "detailLine", tier: "route", source: SOURCE.segments, type: "line", visible: state.visible, paint: { "line-color": state.segmentColor, "line-width": ROUTE.lineWidthsPx.detail } }),
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
          { role: "arrowHalo", tier: "route" as const, source: SOURCE.selected, type: "symbol" as const, visible: state.visible, layout: { "icon-image": state.arrowIconImage, "symbol-placement": "line", "symbol-spacing": ROUTE.arrowSpacingPx, "icon-allow-overlap": true, "icon-ignore-placement": true, "icon-size": arrowSize(ROUTE.arrowHaloScale) }, paint: { "icon-color": palette.semantic.route_arrow_halo, "icon-opacity": 0.95 } },
          { role: "arrow", tier: "route" as const, source: SOURCE.selected, type: "symbol" as const, visible: state.visible, layout: { "icon-image": state.arrowIconImage, "symbol-placement": "line", "symbol-spacing": ROUTE.arrowSpacingPx, "icon-allow-overlap": true, "icon-ignore-placement": true, "icon-size": arrowSize(1) }, paint: { "icon-color": palette.semantic.route_arrow, "icon-opacity": 1 } },
        ]),
  ];

  return { sources, layers };
});

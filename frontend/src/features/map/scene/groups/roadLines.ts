/** 道路そのものの線（路面の種類・道路の種類・トンネル・一方通行）と、詳細を見ている
 * 1本の道の強調。
 *
 * **何を線で描くかはここが宣言する**。描ける属性の一覧は源泉（生成物`primaryAttributes.ts`の
 * `geometry="line"`）が持ち、そのうちどれを出すかは画面の判断——分類と色を宣言したものが
 * 出る。タイルのプロパティ名は属性idと同じ綴りで、対応表を別に持たない。
 *
 * すべて**同じ路面タイルのソース**を共有する。評価軸の線も同じソースを読むため、
 * ソースの宣言は合成（`composeScene`）が1本へ畳む。
 *
 * **同じ道へ複数の線を重ねると後から描いた方が隠す**ので、出ている線を横へ割り付ける（1本なら中央）。
 * 分類を運ぶのは色で、太さは順序のある分類の行だけが色と同じ順序を重ねて示し、線種が運ぶのは値が無いこと
 * （タグが無い道）だけ——1本の線へ2つの分類を載せると、色の意味がもう一方のON/OFFで入れ替わる。
 */
import { sceneSourceId } from "@/features/map/scene/sceneBuilders";
import { mapDisplay } from "@/types/generated/mapDisplay";
import palette from "@/types/generated/palette.json";
import type { FilterSpecification } from "maplibre-gl";

import { primaryAttributes } from "@/types/generated/primaryAttributes";

import { COLOR_UNKNOWN, noDataDashExpression } from "@/features/map/scene/sceneBuilders";
import { LEGEND_NO_DATA_KEY } from "@/lib/mapDisplay/mapColorLegend";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "@/features/map/scene/mapSceneGroups";

const ROAD = mapDisplay.road;

export const ROAD_LINE_SOURCE_ID = sceneSourceId("road-tiles");
/** 押したときに拾う対象。道路の線はどれも共通の名前を名乗る。 */
const ROAD_LINE_HIT_TARGET = "road";

/** 地物へ安定したidを与えるための昇格先。**この綴りでなければ feature-state が効かない**
 * ——タイルの地物はズームによって道1本にも区間にもなり、この列だけがその単位に追従する。 */
const FEATURE_KEY_PROPERTY = "feature_key";
/** 詳細の強調が突き合わせる列（道1本の単位）。 */
const WAY_ID_PROPERTY = "osm_way_id";

/** 線で描くもの。**源泉が「線の幾何を持ち、表示の定義がある」と言ったものが出る。**
 * 束ね方・行の名前・並び・色はすべて源泉が決め、ここは受け取って塗るだけ
 * （`backend/app/domain/material_catalog.py`の`display_axes`、色は`display_palette.py`）。 */
export const ROAD_TRACKS = primaryAttributes.filter(
  (attr): attr is Extract<typeof attr, { geometry: "line"; tile_kind: string }> =>
    attr.geometry === "line" && attr.display_axes.length > 0,
);

type RoadTrack = (typeof ROAD_TRACKS)[number];

/** 線は軸を1本しか持たない（プロパティ＝属性そのもの）。**軸を持つものだけを線にする**のは
 * 源泉の側で、そこが保証する（`tests/test_primary_attribute_display.py`）。 */
export function roadTrackAxis(track: RoadTrack): RoadTrack["display_axes"][number] {
  return track.display_axes[0];
}

export type RoadLineState = {
  /** タイルの配信先。**世代が届くまでは null**。 */
  readonly tiles: {
    readonly urls: readonly string[];
    readonly sourceLayer: string;
    readonly minZoom: number;
    readonly maxZoom: number;
  } | null;
  /** 属性idごとの表示ON/OFF。 */
  readonly visible: Readonly<Record<string, boolean>>;
  /** 属性idごとの、凡例で隠した行の鍵。 */
  readonly hiddenKeys: Readonly<Record<string, readonly string[]>>;
  /** 詳細を見ている道。開いていなければ null。 */
  readonly inspectedWayId: number | null;
};

/** 凡例の「その他」（タグはあるが、どの分類にも当てはまらない値）の鍵。分類の鍵・「不明」の鍵と重ならない
 * （`legends.test.ts`が全属性で確かめる）。 */
export const ROAD_OTHER_KEY = "other";

/** 値を引く式。プロパティが無い道はどの分類にも当たらない空文字へ倒す
 * （欠落のまま比べると式の評価が落ちる）。 */
function valueOf(track: RoadTrack): unknown {
  return ["coalesce", ["get", roadTrackAxis(track).property], ""];
}

/** 値の無い道がタイルに現れうるか。**源泉の宣言が決める**（その値を載せる材料の欠け方`missing_semantics`）
 * ——トンネル・一方通行のように、タグの不在も「該当しない」という確定した値として載る属性がある。 */
export function roadTrackHasMissing(track: RoadTrack): boolean {
  return roadTrackAxis(track).missing_semantics === "unknown";
}

/** タグが無い道（本当に不明）。タグはあるが分類に当てはまらない道（その他）とは分ける——前者は値が無く、
 * 後者は値があって種類が分類の外にあるだけ。 */
function missingOf(track: RoadTrack): unknown {
  return ["==", valueOf(track), ""];
}

function knownValues(track: RoadTrack): readonly unknown[] {
  return roadTrackAxis(track).categories.flatMap((category) => [...category.values]);
}

function colorExpression(track: RoadTrack): unknown[] {
  const value = valueOf(track);
  const cases = roadTrackAxis(track).categories.flatMap((category) => [
    ["in", value, ["literal", [...category.values]]],
    category.color,
  ]);
  return ["case", ...cases, COLOR_UNKNOWN];
}

/** 太さ（px）か、道ごとに太さを決める式。行の太さは源泉が配り（順序のある分類だけが持つ）、持たない行と
 * その他・不明は共通の太さ。 */
type WidthPx = number | unknown[];

/** 行の道を描く太さ。凡例の見本も同じ値を使う。 */
export function roadCategoryWidthPx(category: RoadTrack["display_axes"][number]["categories"][number]): number {
  return "line_width_px" in category ? category.line_width_px : ROAD.lineWidthPx;
}

function widthExpression(track: RoadTrack): WidthPx {
  const categories = roadTrackAxis(track).categories;
  if (categories.every((category) => roadCategoryWidthPx(category) === ROAD.lineWidthPx)) return ROAD.lineWidthPx;
  const value = valueOf(track);
  const cases = categories.flatMap((category) => [
    ["in", value, ["literal", [...category.values]]],
    roadCategoryWidthPx(category),
  ]);
  return ["case", ...cases, ROAD.lineWidthPx];
}

function roadTrackMaxWidthPx(track: RoadTrack): number {
  return Math.max(ROAD.lineWidthPx, ...roadTrackAxis(track).categories.map(roadCategoryWidthPx));
}

/** 道路の線がすべて出て、どれも最も太いときの帯の幅。 */
export const ROAD_TRACKS_MAX_SPAN_PX =
  ROAD_TRACKS.reduce((total, track) => total + roadTrackMaxWidthPx(track), 0) -
  Math.max(0, ROAD_TRACKS.length - 1) * ROAD.trackOverlapPx;

function sumPx(terms: readonly WidthPx[]): WidthPx {
  const constant = terms.reduce<number>((total, term) => (typeof term === "number" ? total + term : total), 0);
  const variable = terms.filter((term) => typeof term !== "number");
  return variable.length === 0 ? constant : ["+", constant, ...variable];
}

function scalePx(factor: number, term: WidthPx): WidthPx {
  return typeof term === "number" ? factor * term : ["*", factor, term];
}

/** 出ている線それぞれの横位置。隣どうしは互いの太さの半分ずつ離し、`trackOverlapPx`だけ重ねる——太さが道ごとに
 * 違うので、位置も道ごとの式になる。帯全体の中央を道の位置へ置く。
 * i本目の位置 = (手前の線の太さの和 − 奥の線の太さの和)/2 + ((本数−1)/2 − i)×重ね幅。 */
function offsetsFor(widths: readonly WidthPx[]): readonly WidthPx[] {
  const overlap = ROAD.trackOverlapPx;
  return widths.map((_, index) =>
    sumPx([
      ((widths.length - 1) / 2 - index) * overlap,
      scalePx(0.5, sumPx(widths.slice(0, index))),
      scalePx(-0.5, sumPx(widths.slice(index + 1))),
    ]),
  );
}

/** 分類に入る道は濃く、それ以外（その他・不明）は薄く（消さずに薄くする）。 */
function opacityExpression(track: RoadTrack): unknown[] {
  return ["case", ["in", valueOf(track), ["literal", [...knownValues(track)]]], ROAD.knownOpacity, ROAD.unknownOpacity];
}

function trackFilter(track: RoadTrack, hiddenKeys: readonly string[]): FilterSpecification | undefined {
  const hidden = roadTrackAxis(track).categories.filter((category) => hiddenKeys.includes(category.key));
  const values = hidden.flatMap((category) => [...category.values]);
  const conditions: unknown[] = [];
  if (values.length > 0) conditions.push(["!", ["in", valueOf(track), ["literal", values]]]);
  const hasMissing = roadTrackHasMissing(track);
  if (hiddenKeys.includes(ROAD_OTHER_KEY)) {
    const known: unknown[] = ["in", valueOf(track), ["literal", [...knownValues(track)]]];
    conditions.push(hasMissing ? ["any", missingOf(track), known] : known);
  }
  if (hasMissing && hiddenKeys.includes(LEGEND_NO_DATA_KEY)) conditions.push(["!", missingOf(track)]);
  if (conditions.length === 0) return undefined;
  return ["all", ...conditions] as unknown as FilterSpecification;
}

export const roadLineGroup = declareGroup<RoadLineState>((state) => {
  if (state.tiles === null) return { sources: [], layers: [] };
  const tiles = state.tiles;

  const sources: readonly SceneSourceEntry[] = [
    {
      id: ROAD_LINE_SOURCE_ID,
      spec: {
        type: "vector",
        minzoom: tiles.minZoom,
        maxzoom: tiles.maxZoom,
        promoteId: { [tiles.sourceLayer]: FEATURE_KEY_PROPERTY },
      },
      sourceLayer: tiles.sourceLayer,
      tiles: tiles.urls,
    },
  ];

  const shown = ROAD_TRACKS.filter((track) => state.visible[track.attr_id] === true);
  const offsets = offsetsFor(shown.map(widthExpression));
  const offsetOf = new Map(shown.map((track, index) => [track.attr_id, offsets[index] ?? 0]));

  const layers: SceneLayerEntry[] = ROAD_TRACKS.map((track) => ({
    role: track.attr_id,
    tier: "observedLine",
    source: ROAD_LINE_SOURCE_ID,
    sourceLayer: tiles.sourceLayer,
    type: "line",
    paint: {
      "line-color": colorExpression(track),
      "line-width": widthExpression(track),
      "line-opacity": opacityExpression(track),
      ...(roadTrackHasMissing(track) ? { "line-dasharray": noDataDashExpression(missingOf(track)) } : {}),
      "line-offset": offsetOf.get(track.attr_id) ?? 0,
    },
    visible: state.visible[track.attr_id] === true,
    hitTargets: [ROAD_LINE_HIT_TARGET],
    ...(trackFilter(track, state.hiddenKeys[track.attr_id] ?? []) === undefined
      ? {}
      : { filter: trackFilter(track, state.hiddenKeys[track.attr_id] ?? []) }),
  }));

  layers.push({
    role: "inspected",
    tier: "observedLine",
    source: ROAD_LINE_SOURCE_ID,
    sourceLayer: tiles.sourceLayer,
    type: "line",
    paint: { "line-color": palette.semantic.inspected, "line-width": ROAD.inspectedWidthPx, "line-opacity": 1 },
    visible: state.inspectedWayId !== null,
    filter: ["==", ["get", WAY_ID_PROPERTY], state.inspectedWayId ?? -1] as unknown as FilterSpecification,
  });

  return { sources, layers };
});

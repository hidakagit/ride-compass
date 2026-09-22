/** 道路そのものの線（路面の種類・道路の種類・トンネル・一方通行）と、詳細を見ている
 * 1本の道の強調。
 *
 * **何を線で描くかはここが宣言する**。描ける属性の一覧は源泉（`primary-attributes.json`の
 * `geometry="line"`）が持ち、そのうちどれを出すかは画面の判断——分類と色を宣言したものが
 * 出る。タイルのプロパティ名は属性idと同じ綴りで、対応表を別に持たない。
 *
 * すべて**同じ路面タイルのソース**を共有する。評価軸の線も同じソースを読むため、
 * ソースの宣言は合成（`composeScene`）が1本へ畳む。
 *
 * **同じ道へ複数の線を重ねると後から描いた方が隠す**ので、出ている本数から対称に
 * 横へ割り付ける（1本なら中央）。線の太さと線種は意味を運ばない——1本の線へ2つの意味を
 * 載せると、色の意味がもう一方のON/OFFで入れ替わる。
 */
import type { FilterSpecification } from "maplibre-gl";

import { COLOR_UNKNOWN } from "@/components/Map/axisLayers";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";

const LINE_WIDTH_PX = 3;
/** 横へ分けるときの間隔。線の太さより狭くして、隣どうしがわずかに重なるようにする
 * （離すと1本の道が複数に見える）。 */
const TRACK_OFFSET_STEP_PX = 2;
/** 分類がある道は濃く、無い道は薄く（消さずに薄くする）。 */
export const KNOWN_LINE_OPACITY = 0.8;
export const UNKNOWN_LINE_OPACITY = 0.15;
/** 詳細を見ている道の強調。線の色に関係なく浮く色にする。 */
const INSPECTED_COLOR = "#f59e0b";
const INSPECTED_WIDTH_PX = 8;

export const ROAD_LINE_SOURCE_ID = "road-tiles";
/** 押したときに拾う対象。道路の線はどれも共通の名前を名乗る。 */
export const ROAD_LINE_HIT_TARGET = "road";

/** 地物へ安定したidを与えるための昇格先。**この綴りでなければ feature-state が効かない**
 * ——タイルの地物はズームによって道1本にも区間にもなり、この列だけがその単位に追従する。 */
const FEATURE_KEY_PROPERTY = "feature_key";
/** 詳細の強調が突き合わせる列（道1本の単位）。 */
const WAY_ID_PROPERTY = "osm_way_id";

/** 凡例の1行。複数の値を1行へまとめられる。 */
export type RoadCategory = {
  readonly key: string;
  readonly label: string;
  readonly color: string;
  readonly values: readonly (string | boolean)[];
};

/** 線1本ぶんの宣言。**属性idがそのままタイルのプロパティ名・レイヤーの役割になる。**
 * 名前は源泉（`primary-attributes.json`のlabel）が持つのでここには書かない。 */
export type RoadTrackDecl = {
  /** 源泉（`primary-attributes.json`）の一次属性id。 */
  readonly attrId: string;
  readonly categories: readonly RoadCategory[];
};

// ルート候補線（選択=青・未選択=アンバー）と紛れないよう、道の分類には青を使わない。
const COLOR_ASPHALT = "#64748b";
const COLOR_CONCRETE = "#0d9488";
const COLOR_STONES = "#7c3aed";
const COLOR_GRAVEL = "#a3915f";
const COLOR_DIRT = "#92400e";

/** 幹線ほど濃い、色相を持たない濃淡。順序はあるが良し悪しではないため、評価軸の
 * 緑〜赤とは別の視覚言語にする。 */
const COLOR_HIGHWAY_ARTERIAL = "#334155";
const COLOR_HIGHWAY_SECONDARY = "#475569";
const COLOR_HIGHWAY_LOCAL = "#94a3b8";
const COLOR_HIGHWAY_MINOR = "#cbd5e1";

/** トンネルは夜間の評価で不利に働くため、評価軸の危険側と同じ色で出す。 */
const COLOR_TUNNEL = "#f97316";
/** 一方通行はどの評価軸の材料でもないため、評価色を避ける。 */
const COLOR_ONEWAY = "#2563eb";

/** 線で描く属性。**ここへ1件足すと線が1本増える**（レイヤーid・タイルのプロパティ・
 * 凡例・横位置はすべてここから決まる）。 */
export const ROAD_TRACKS: readonly RoadTrackDecl[] = [
  {
    attrId: "surface",
    categories: [
      { key: "asphalt", label: "アスファルト", color: COLOR_ASPHALT, values: ["asphalt", "paved", "chipseal"] },
      {
        key: "concrete",
        label: "コンクリート",
        color: COLOR_CONCRETE,
        values: ["concrete", "concrete:plates", "concrete:lanes"],
      },
      {
        // backendの正準分類で良い側（paving_stones・bricks）と悪い側（sett・cobblestone等）が
        // 混じる唯一の行。材質として同類なので良否で割らず、色も良し悪しを示さない紫にする。
        key: "stones",
        label: "石畳・敷石",
        color: COLOR_STONES,
        values: ["paving_stones", "sett", "cobblestone", "unhewn_cobblestone", "bricks"],
      },
      {
        key: "gravel",
        label: "砂利・締固め",
        color: COLOR_GRAVEL,
        values: ["gravel", "fine_gravel", "compacted", "pebblestone", "rock"],
      },
      {
        key: "dirt",
        label: "土・草・砂",
        color: COLOR_DIRT,
        values: ["unpaved", "dirt", "ground", "earth", "mud", "sand", "grass", "woodchips"],
      },
    ],
  },
  {
    attrId: "highway",
    categories: [
      {
        key: "arterial",
        label: "幹線道路",
        color: COLOR_HIGHWAY_ARTERIAL,
        values: ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"],
      },
      {
        key: "secondary",
        label: "主要道",
        color: COLOR_HIGHWAY_SECONDARY,
        values: ["secondary", "secondary_link", "tertiary", "tertiary_link"],
      },
      {
        key: "local",
        label: "生活道路",
        color: COLOR_HIGHWAY_LOCAL,
        values: ["residential", "unclassified", "living_street", "service", "road"],
      },
      {
        key: "cycleway",
        label: "自転車・歩行者道",
        color: COLOR_HIGHWAY_MINOR,
        values: ["cycleway", "path", "footway", "pedestrian", "bridleway", "steps"],
      },
      // 自転車・歩行者道と濃淡が近く見分けが付かないため、未舗装路のイメージが重なる
      // 土の色を流用する（別のトラックへ分かれるので画面上で直接は競合しない）。
      { key: "track", label: "農道・林道", color: COLOR_DIRT, values: ["track"] },
    ],
  },
  {
    attrId: "tunnel",
    categories: [{ key: "tunnel", label: "トンネル", color: COLOR_TUNNEL, values: [true] }],
  },
  {
    attrId: "oneway",
    categories: [{ key: "oneway", label: "一方通行", color: COLOR_ONEWAY, values: [true] }],
  },
];

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

/** 値を引く式。プロパティが無い道はどの分類にも当たらない空文字へ倒す
 * （欠落のまま比べると式の評価が落ちる）。 */
function valueOf(track: RoadTrackDecl): unknown {
  return ["coalesce", ["get", track.attrId], ""];
}

function colorExpression(track: RoadTrackDecl): unknown[] {
  const value = valueOf(track);
  const cases = track.categories.flatMap((category) => [
    ["in", value, ["literal", [...category.values]]],
    category.color,
  ]);
  return ["case", ...cases, COLOR_UNKNOWN];
}

function opacityExpression(track: RoadTrackDecl): unknown[] {
  const known = track.categories.flatMap((category) => [...category.values]);
  return ["case", ["in", valueOf(track), ["literal", known]], KNOWN_LINE_OPACITY, UNKNOWN_LINE_OPACITY];
}

function trackFilter(track: RoadTrackDecl, hiddenKeys: readonly string[]): FilterSpecification | undefined {
  const hidden = track.categories.filter((category) => hiddenKeys.includes(category.key));
  const values = hidden.flatMap((category) => [...category.values]);
  if (values.length === 0) return undefined;
  return ["!", ["in", valueOf(track), ["literal", values]]] as unknown as FilterSpecification;
}

/** 出ている本数から、対称に割り付けた横位置。1本なら0。 */
function offsetsFor(visibleCount: number): readonly number[] {
  return Array.from({ length: visibleCount }, (_, index) => (index - (visibleCount - 1) / 2) * TRACK_OFFSET_STEP_PX);
}

export const roadLineGroup = declareGroup<RoadLineState>("road", (state) => {
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

  const shown = ROAD_TRACKS.filter((track) => state.visible[track.attrId] === true);
  const offsets = offsetsFor(shown.length);
  const offsetOf = new Map(shown.map((track, index) => [track.attrId, offsets[index] ?? 0]));

  const layers: SceneLayerEntry[] = ROAD_TRACKS.map((track) => ({
    role: track.attrId,
    tier: "observedLine",
    source: ROAD_LINE_SOURCE_ID,
    sourceLayer: tiles.sourceLayer,
    type: "line",
    paint: {
      "line-color": colorExpression(track),
      "line-width": LINE_WIDTH_PX,
      "line-opacity": opacityExpression(track),
      "line-offset": offsetOf.get(track.attrId) ?? 0,
    },
    visible: state.visible[track.attrId] === true,
    hitTargets: [ROAD_LINE_HIT_TARGET],
    ...(trackFilter(track, state.hiddenKeys[track.attrId] ?? []) === undefined
      ? {}
      : { filter: trackFilter(track, state.hiddenKeys[track.attrId] ?? []) }),
  }));

  layers.push({
    role: "inspected",
    tier: "observedLine",
    source: ROAD_LINE_SOURCE_ID,
    sourceLayer: tiles.sourceLayer,
    type: "line",
    paint: { "line-color": INSPECTED_COLOR, "line-width": INSPECTED_WIDTH_PX, "line-opacity": 1 },
    visible: state.inspectedWayId !== null,
    filter: ["==", ["get", WAY_ID_PROPERTY], state.inspectedWayId ?? -1] as unknown as FilterSpecification,
  });

  return { sources, layers };
});

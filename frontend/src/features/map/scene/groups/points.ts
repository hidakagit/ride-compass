/** 点で示すもの（停止要因POI・補給休憩POI・事故地点）。
 *
 * **何を点で描くかはここが宣言する**。点になりうる属性は源泉（`primary-attributes.json`の
 * `geometry="point"`）が持ち、そのうちどれを出すかは画面の判断——分類と色を宣言したものが
 * 出る（交差点は道路網を見れば分かるので出さない）。
 *
 * 停止要因と補給は**同じソース・同じsource-layerを共有し、種別の集合で分ける**——
 * 分ける条件を持たないと互いの点が混ざる。その集合は源泉（`poi-kinds.json`）から取る
 * ので、backendが種別を増やしたときに地図から消えることはない（色だけが未分類になる）。
 * 事故は配信の系統が違うため別のソース。
 *
 * **タイルの世代が届くまでソースを作らない**。先に作ると、世代の違う中身がブラウザの
 * キャッシュへ載って以後ずっと残る。
 */
import type { FilterSpecification } from "maplibre-gl";

import poiKinds from "@/types/generated/poi-kinds.json";

import { COLOR_UNKNOWN } from "@/components/Map/axisLayers";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";

const RADIUS_PX = 4;
/** 死亡事故だけは大きく出す（重大度は色ではなく大きさで示し、当事者の色と取り合わない）。 */
const FATAL_RADIUS_PX = 6;
const NON_FATAL_RADIUS_PX = 3;
const STROKE_WIDTH_PX = 1;
const STROKE_COLOR = "#ffffff";
const OPACITY = 0.9;
const ACCIDENT_OPACITY = 0.75;

const KIND_PROPERTY = "kind";
const INVOLVES_BICYCLE_PROPERTY = "involves_bicycle";
const FATAL_PROPERTY = "fatal";

// POIの種別は評価へ効く（停止密度の材料になる）が、種別ごとの重みは軸定義が持ち運用で
// 入れ替わるため、順序を表す評価配色（緑〜赤）は使わず色相で分ける。
const COLOR_INDIGO = "#4f46e5";
const COLOR_BLUE = "#2563eb";
const COLOR_STONE = "#78716c";
const COLOR_PINK = "#be185d";
const COLOR_VIOLET = "#7c3aed";
const COLOR_SLATE = "#475569";
const COLOR_TEAL = "#0d9488";
const COLOR_CYAN = "#0891b2";
const COLOR_SKY = "#7dd3fc";
/** 事故のうち評価へ寄与する側（自転車関連）は、評価軸の危険側と同じ赤で出す。 */
const COLOR_ACCIDENT_BICYCLE = "#dc2626";
const COLOR_ACCIDENT_OTHER = "#6b7280";

/** 凡例の1行。複数の値を1行へまとめられる——利用者から見て区別する意味の無い種別
 * （車道用の踏切と歩道用の踏切）を分けて並べない。 */
export type PointCategory = {
  readonly key: string;
  readonly label: string;
  readonly color: string;
  readonly values: readonly (string | boolean)[];
};

/** 絞り込みの軸。1つの点に複数の軸があるときは、すべてANDで効く。色は先頭の軸が決める。 */
export type PointAxis = {
  readonly key: string;
  /** 軸が1本だけなら見出しは要らない（レイヤー名で足りる）。 */
  readonly label?: string;
  readonly property: string;
  readonly categories: readonly PointCategory[];
};

export type PointSourceKey = "poi" | "accident";

export type PointLayerDecl = {
  /** 源泉（`primary-attributes.json`）の一次属性id。名前もそこが持つ。 */
  readonly role: string;
  readonly source: PointSourceKey;
  readonly axes: readonly PointAxis[];
  /** 凡例の操作に関わらず常に効く絞り込み（同じタイルを分け合う点で使う）。 */
  readonly baseFilter?: FilterSpecification;
};

function kindIn(values: readonly string[]): FilterSpecification {
  return ["in", ["get", KIND_PROPERTY], ["literal", [...values]]] as unknown as FilterSpecification;
}

/** 点で描くもの。**ここへ1件足すと点のレイヤーが1枚増える**。 */
export const POINT_LAYERS: readonly PointLayerDecl[] = [
  {
    role: "stop_poi",
    source: "poi",
    baseFilter: kindIn(poiKinds.stop),
    axes: [
      {
        key: "kind",
        property: KIND_PROPERTY,
        categories: [
          { key: "traffic_signals", label: "信号", color: COLOR_INDIGO, values: ["traffic_signals"] },
          { key: "crossing", label: "横断歩道", color: COLOR_BLUE, values: ["crossing"] },
          { key: "stop", label: "一時停止", color: COLOR_STONE, values: ["stop"] },
          { key: "give_way", label: "徐行", color: COLOR_PINK, values: ["give_way"] },
          // 車道用と歩道・自転車道用の踏切は、利用者から見れば同じ「線路を渡る点」。
          {
            key: "level_crossing",
            label: "踏切",
            color: COLOR_VIOLET,
            values: ["level_crossing", "railway_crossing"],
          },
          { key: "barrier", label: "車止め・ゲート", color: COLOR_SLATE, values: ["barrier"] },
          { key: "traffic_calming", label: "ハンプ・狭さく", color: COLOR_TEAL, values: ["traffic_calming"] },
        ],
      },
    ],
  },
  {
    role: "supply_poi",
    source: "poi",
    baseFilter: kindIn(poiKinds.supply),
    axes: [
      {
        key: "kind",
        property: KIND_PROPERTY,
        categories: [
          { key: "convenience", label: "コンビニ", color: COLOR_INDIGO, values: ["convenience"] },
          // 自販機は「ここで飲み物が買える」という約束として読まれる。中身が分からない
          // ものを同じ確からしさに見せない。
          { key: "vending_drinks", label: "飲料自販機", color: COLOR_CYAN, values: ["vending_drinks"] },
          { key: "vending_unknown", label: "自販機(中身不明)", color: COLOR_SKY, values: ["vending_unknown"] },
          { key: "toilets", label: "トイレ", color: COLOR_BLUE, values: ["toilets"] },
          { key: "drinking_water", label: "給水", color: COLOR_TEAL, values: ["drinking_water"] },
          { key: "bicycle_parking", label: "駐輪場", color: COLOR_STONE, values: ["bicycle_parking"] },
        ],
      },
    ],
  },
  {
    role: "accident_point",
    source: "accident",
    axes: [
      {
        key: "party",
        label: "当事者",
        property: INVOLVES_BICYCLE_PROPERTY,
        categories: [
          // 自転車関連だけが事故密度の材料になる（寄与しない側は中立色のまま）。
          { key: "bicycle", label: "自転車関連", color: COLOR_ACCIDENT_BICYCLE, values: [true] },
          { key: "other", label: "その他", color: COLOR_ACCIDENT_OTHER, values: [false] },
        ],
      },
      {
        key: "severity",
        label: "重大度",
        property: FATAL_PROPERTY,
        categories: [
          { key: "fatal", label: "死亡事故", color: COLOR_ACCIDENT_BICYCLE, values: [true] },
          { key: "non_fatal", label: "死亡以外", color: COLOR_ACCIDENT_OTHER, values: [false] },
        ],
      },
    ],
  },
];

export type PointState = {
  /** タイルの配信先。**世代が届くまでは null**——その間は何も作らない。 */
  readonly tiles: {
    readonly poi: readonly string[];
    readonly accident: readonly string[];
    readonly poiSourceLayer: string;
    readonly accidentSourceLayer: string;
    readonly minZoom: number;
    readonly maxZoom: number;
  } | null;
  /** 役割ごとの表示ON/OFF。 */
  readonly visible: Readonly<Record<string, boolean>>;
  /** 軸の鍵ごとの、凡例で隠した行の鍵。 */
  readonly hiddenKeys: Readonly<Record<string, readonly string[]>>;
};

export const POINT_SOURCE_ID: Record<PointSourceKey, string> = { poi: "point-poi", accident: "point-accident" };

/** 押したときに拾う対象。**どの点も共通の`point`を名乗る**ので、点を1枚足しても
 * 拾う側の判定は変わらない。 */
export const POINT_HIT_TARGET = "point";

/** 軸の絞り込みの鍵。役割をまたいで同じ軸名を使えるようにする。 */
export function pointAxisKey(layer: PointLayerDecl, axis: PointAxis): string {
  return `${layer.role}:${axis.key}`;
}

function valueOf(axis: PointAxis): unknown {
  return ["get", axis.property];
}

/** 分類ごとの色。隠した行も含めて作る——隠しても残った分類の色が動かないようにする。 */
function colorExpression(layer: PointLayerDecl): unknown {
  const axis = layer.axes[0];
  // 行が1つも無いときに`case`を出すと、対を持たない式になって地図が受け付けない。
  if (axis === undefined || axis.categories.length === 0) return COLOR_UNKNOWN;
  const cases = axis.categories.flatMap((category) => [
    ["in", valueOf(axis), ["literal", [...category.values]]],
    category.color,
  ]);
  return ["case", ...cases, COLOR_UNKNOWN];
}

/** 通す分類だけを残す絞り込み。軸が複数あるときはすべてANDで効く。 */
function layerFilter(layer: PointLayerDecl, hiddenKeys: PointState["hiddenKeys"]): FilterSpecification | undefined {
  const clauses: unknown[] = [];
  if (layer.baseFilter !== undefined) clauses.push(layer.baseFilter);
  for (const axis of layer.axes) {
    const hidden = hiddenKeys[pointAxisKey(layer, axis)] ?? [];
    if (hidden.length === 0) continue;
    const values = axis.categories.filter((c) => hidden.includes(c.key)).flatMap((c) => [...c.values]);
    if (values.length === 0) continue;
    clauses.push(["!", ["in", valueOf(axis), ["literal", values]]]);
  }
  if (clauses.length === 0) return undefined;
  if (clauses.length === 1) return clauses[0] as FilterSpecification;
  return ["all", ...clauses] as unknown as FilterSpecification;
}

/** 重大度の軸を持つ点だけ、大きさでも重大度を示す。 */
function radiusExpression(layer: PointLayerDecl): unknown {
  const severity = layer.axes.find((axis) => axis.property === FATAL_PROPERTY);
  if (severity === undefined) return RADIUS_PX;
  return ["case", ["==", ["get", FATAL_PROPERTY], true], FATAL_RADIUS_PX, NON_FATAL_RADIUS_PX];
}

export const pointGroup = declareGroup<PointState>("point", (state) => {
  if (state.tiles === null) return { sources: [], layers: [] };
  const tiles = state.tiles;

  const sourceLayerOf: Record<PointSourceKey, string> = {
    poi: tiles.poiSourceLayer,
    accident: tiles.accidentSourceLayer,
  };

  const sources: readonly SceneSourceEntry[] = [
    {
      id: POINT_SOURCE_ID.poi,
      spec: { type: "vector", minzoom: tiles.minZoom, maxzoom: tiles.maxZoom },
      sourceLayer: tiles.poiSourceLayer,
      tiles: tiles.poi,
    },
    {
      id: POINT_SOURCE_ID.accident,
      spec: { type: "vector", minzoom: tiles.minZoom, maxzoom: tiles.maxZoom },
      sourceLayer: tiles.accidentSourceLayer,
      tiles: tiles.accident,
    },
  ];

  const layers: readonly SceneLayerEntry[] = POINT_LAYERS.map((layer) => ({
    role: layer.role,
    tier: "point",
    source: POINT_SOURCE_ID[layer.source],
    sourceLayer: sourceLayerOf[layer.source],
    type: "circle",
    paint: {
      "circle-color": colorExpression(layer),
      "circle-radius": radiusExpression(layer),
      "circle-stroke-width": STROKE_WIDTH_PX,
      "circle-stroke-color": STROKE_COLOR,
      "circle-opacity": layer.source === "accident" ? ACCIDENT_OPACITY : OPACITY,
    },
    visible: state.visible[layer.role] === true,
    hitTargets: [POINT_HIT_TARGET, `${POINT_HIT_TARGET}:${layer.role}`],
    ...(layerFilter(layer, state.hiddenKeys) === undefined
      ? {}
      : { filter: layerFilter(layer, state.hiddenKeys) }),
  }));

  return { sources, layers };
});

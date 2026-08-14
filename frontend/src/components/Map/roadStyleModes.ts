// 路面レイヤー（無方向・地域固定データ）の色分けモード定義。
//
// タイル（バックエンドのMVT）にはsurface_good（3値の正準分類）・surface（正規化済み
// OSM生タグ）・highway（OSM道路種別）が焼き込まれており、色分けの切り替えは
// MapLibreのline-color式の差し替えだけで完結する（タイル再取得は発生しない）。
// モードを増やすときは、タイルへプロパティを1つ足し、ここへモード定義を1つ足す。
//
// このファイルが扱うのは「どちら向きに走っても同じ」無方向データのみ。進行方向で
// 意味が変わる有向データ（勾配・風など）は選択中ルート基準の動的レイヤー
// （routeStyleModes.ts）が担当する。勾配を地域レイヤーとして出したくなった場合は、
// 標高を面的にバッチ前計算したうえで絶対値（地形のきつさ）の無方向データとして
// 再導入すること（ルート生成の副産物である標高属性を源にするとカバレッジがルート
// 生成履歴依存になり、「固定で取得しておく」性質を満たせない）。
//
// グルーピングの狙いは「ライドが快適な条件を探す」ための取捨選択であって、OSMタグの
// 網羅的な分類ではない。凡例に出せる5〜6カテゴリまでに抑え、稀なタグはフォールバック
// （不明・その他=グレー）へ落とす。surface_goodによる舗装/未舗装の判定（ルート評価と
// 共通の正準定義、backend/app/domain/road.py）はここのグルーピングとは独立で、
// 本ファイルは表示専用の語彙とする。
//
// 各凡例エントリは「この地物がそのカテゴリに属するか」の述語（filter）を持ち、
// 凡例タップによるカテゴリの表示/非表示（legendFilter.ts）に使う。

import type { LegendEntry } from "./legendFilter";

export type RoadStyleModeId = "paved" | "surface" | "highway";

export interface RoadStyleMode {
  id: RoadStyleModeId;
  /** モード選択メニューに出す名前 */
  label: string;
  legend: LegendEntry[];
  /** MapLibreのline-colorに渡すスタイル式 */
  colorExpression: unknown[];
}

// 既存の配色（良い=緑・悪い=赤・不明=グレー、風の普通=アンバー）と整合させたパレット。
// ルート候補線（選択=青#2563eb・未選択=アンバー#f59e0b）と紛れにくいよう、青は使わず
// 生活道路には空色を当てる。
const COLOR_GOOD = "#16a34a";
const COLOR_BAD = "#dc2626";
const COLOR_UNKNOWN = "#9ca3af";
const COLOR_TEAL = "#0d9488";
const COLOR_VIOLET = "#7c3aed";
const COLOR_AMBER = "#d97706";
const COLOR_BROWN = "#92400e";
const COLOR_SKY = "#0284c7";

interface CategoryGroup {
  key: string;
  label: string;
  color: string;
  /** このカテゴリに含めるタグ値（タイル側で正規化済みの小文字） */
  values: string[];
}

// OSMのsurfaceタグの表示用グルーピング。タグ値はバックエンド側でlower/trim正規化済み。
const SURFACE_GROUPS: CategoryGroup[] = [
  { key: "asphalt", label: "アスファルト", color: COLOR_GOOD, values: ["asphalt", "paved", "chipseal"] },
  {
    key: "concrete",
    label: "コンクリート",
    color: COLOR_TEAL,
    values: ["concrete", "concrete:plates", "concrete:lanes"],
  },
  {
    key: "stones",
    label: "石畳・敷石",
    color: COLOR_VIOLET,
    values: ["paving_stones", "sett", "cobblestone", "unhewn_cobblestone", "bricks"],
  },
  {
    key: "gravel",
    label: "砂利・締固め",
    color: COLOR_AMBER,
    values: ["gravel", "fine_gravel", "compacted", "pebblestone", "rock"],
  },
  {
    key: "dirt",
    label: "土・草・砂",
    color: COLOR_BROWN,
    values: ["unpaved", "dirt", "ground", "earth", "mud", "sand", "grass", "woodchips"],
  },
];

// OSMのhighwayタグ（道路種別）の表示用グルーピング。
const HIGHWAY_GROUPS: CategoryGroup[] = [
  {
    key: "arterial",
    label: "幹線道路",
    color: COLOR_BAD,
    values: ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"],
  },
  {
    key: "secondary",
    label: "主要道",
    color: COLOR_AMBER,
    values: ["secondary", "secondary_link", "tertiary", "tertiary_link"],
  },
  {
    key: "local",
    label: "生活道路",
    color: COLOR_SKY,
    values: ["residential", "unclassified", "living_street", "service", "road"],
  },
  {
    key: "cycleway",
    label: "自転車・歩行者道",
    color: COLOR_GOOD,
    values: ["cycleway", "path", "footway", "pedestrian", "bridleway", "steps"],
  },
  { key: "track", label: "農道・林道", color: COLOR_BROWN, values: ["track"] },
];

// プロパティ欠落（["get", field]がnull）のままmatchへ渡すと入力型不一致の評価エラーに
// なりうるため、coalesceで空文字（どのカテゴリのタグ値にも一致しない）へ倒してから
// 判定する。カテゴリ外の未知タグも同様にフォールバックへ落ちる。
function matchInput(field: string): unknown[] {
  return ["coalesce", ["get", field], ""];
}

function buildMatchExpression(field: string, groups: CategoryGroup[]): unknown[] {
  const expression: unknown[] = ["match", matchInput(field)];
  for (const group of groups) {
    expression.push(group.values, group.color);
  }
  expression.push(COLOR_UNKNOWN);
  return expression;
}

function buildGroupLegend(field: string, groups: CategoryGroup[]): LegendEntry[] {
  const allValues = groups.flatMap((group) => group.values);
  return [
    ...groups.map(({ key, color, label, values }) => ({
      key,
      color,
      label,
      filter: ["match", matchInput(field), values, true, false],
    })),
    {
      key: "unknown",
      color: COLOR_UNKNOWN,
      label: "不明・他",
      // どの既知カテゴリのタグ値にも一致しない（タグ無し含む）ものがフォールバック
      filter: ["match", matchInput(field), allValues, false, true],
    },
  ];
}

export const ROAD_STYLE_MODES: RoadStyleMode[] = [
  {
    id: "paved",
    label: "舗装/未舗装",
    legend: [
      { key: "good", color: COLOR_GOOD, label: "舗装路", filter: ["==", ["get", "surface_good"], true] },
      { key: "bad", color: COLOR_BAD, label: "未舗装等", filter: ["==", ["get", "surface_good"], false] },
      { key: "unknown", color: COLOR_UNKNOWN, label: "不明", filter: ["==", ["get", "surface_good"], null] },
    ],
    colorExpression: [
      "case",
      ["==", ["get", "surface_good"], null],
      COLOR_UNKNOWN,
      ["==", ["get", "surface_good"], true],
      COLOR_GOOD,
      COLOR_BAD,
    ],
  },
  {
    id: "surface",
    label: "路面の種類",
    legend: buildGroupLegend("surface", SURFACE_GROUPS),
    colorExpression: buildMatchExpression("surface", SURFACE_GROUPS),
  },
  {
    id: "highway",
    label: "道路の種類",
    legend: buildGroupLegend("highway", HIGHWAY_GROUPS),
    colorExpression: buildMatchExpression("highway", HIGHWAY_GROUPS),
  },
];

export const DEFAULT_ROAD_STYLE_MODE_ID: RoadStyleModeId = "paved";

export function isRoadStyleModeId(value: string | null | undefined): value is RoadStyleModeId {
  return ROAD_STYLE_MODES.some((mode) => mode.id === value);
}

export function getRoadStyleMode(id: RoadStyleModeId): RoadStyleMode {
  return ROAD_STYLE_MODES.find((mode) => mode.id === id) ?? ROAD_STYLE_MODES[0];
}

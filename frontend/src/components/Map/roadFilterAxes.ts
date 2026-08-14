// 路面レイヤー（無方向・地域固定データ）の絞り込み軸の定義。
//
// タイル（バックエンドのMVT）にはsurface_good（3値の正準分類）・surface（正規化済み
// OSM生タグ）・highway（OSM道路種別）が焼き込まれている。かつては舗装/未舗装(surface_good)・
// 路面の種類(surface)・道路の種類(highway)の3つを「同時に1つだけ選ぶ色分けモード」として
// 扱っていたが、舗装/未舗装は路面の種類と同じsurfaceタグを2値に粗く束ねただけのもの
// （backend/app/domain/road.pyのGOOD_OSM_SURFACE_TAGS/BAD_OSM_SURFACE_TAGSと、下の
// SURFACE_GROUPSの分類が同一のsurfaceタグに基づく）で、独立した軸ではなかった。
// 「路面の種類=アスファルト」かつ「舗装/未舗装=未舗装」のような組み合わせは常に矛盾するか
// 冗長になるため、AND絞り込みの対象としては意味を持たない。
//
// そのため舗装/未舗装は廃止し、互いに独立な2軸（路面の種類=surfaceタグ、道路の種類=
// highwayタグ）だけを絞り込み軸として残す。この2つは実際のOSMタグとして独立しており
// （同じ道路がどんな路面材質にもどんな道路種別にもなりうる）、組み合わせて絞り込む
// 意味がある。舗装路だけ見たい場合は「路面の種類」で砂利・土のカテゴリを外せば同じ結果に
// なるため、機能的な欠落は無い。
//
// 地図の色分け（line-color）は常に「路面の種類」の配色で固定する（自転車走行の実用上、
// 最も情報量が多い軸のため）。ユーザーが色分け軸を選ぶUIは持たない（絞り込みと色の選択を
// 同じ画面に同居させると、絞り込んだ結果1色しか出ない軸を選べてしまい情報量ゼロになる、
// という混乱があったため）。
//
// 「道路の種類」は色ではなく線の太さ（line-width）で地図に反映する。色を2軸分掛け合わせる
// （最大30通り）と細い線では判別できず凡例も破綻するため、道路の種類には別の視覚チャンネル
// （太さ）を割り当てている。太さは実際の道幅の感覚と一致させ、幹線道路ほど太く・
// 自転車専用道路ほど細くしてある（HIGHWAY_GROUPSのwidth参照）。不明・他はタグが無い/
// 未分類なだけで実際の道幅とは無関係なため、太さでは目立たせず線種（破線、line-dasharray）
// で区別する。
//
// 軸を増やすときは、タイルへプロパティを1つ足し、ROAD_FILTER_AXESへ軸定義を1つ足すだけで
// よい（RoadFilterDialogは軸のリストを汎用的にループして描画するため、UI側の変更は不要）。
// 追加する軸は必ず「他の軸と独立して決まる事実」であること（例のような粒度違いの再掲は
// 避ける）。

import type { LegendEntry } from "./legendFilter";

export type RoadFilterAxisId = "surface" | "highway";

export interface RoadFilterAxis {
  id: RoadFilterAxisId;
  /** 絞り込みパネルの見出しに出す名前（例:「路面の種類で絞り込み」） */
  label: string;
  legend: LegendEntry[];
  /** MapLibreのline-colorに渡すスタイル式。地図には「路面の種類」軸の式のみを使う。 */
  colorExpression: unknown[];
  /** MapLibreのline-widthに渡すスタイル式。色と衝突しないよう、この式を持つ軸（道路の種類）
   * だけが太さで地図に反映される。色軸（路面の種類）は持たない（undefined）。 */
  widthExpression?: unknown[];
  /** MapLibreのline-dasharrayに渡すスタイル式。「不明・他」を実線と区別するために持つ
   * （道路の種類のみ）。他の軸は持たない（undefined）。 */
  dashArrayExpression?: unknown[];
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
  /** line-widthのpx値。太さで地図に反映する軸（道路の種類）のみ設定する。 */
  width?: number;
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

// 「道路の種類」は線の太さで地図に反映する（実際の道幅の感覚に合わせ、幹線道路ほど太く・
// 自転車専用道路ほど細くする）。差が分かりやすいよう、太さは名前付き定数にまとめて
// ここだけで調整できるようにしてある（HIGHWAY_GROUPSの各widthを直接いじらず、この定数を
// 変える）。不明・他はタグ自体が無い/未分類で実際の道幅とは無関係なため、太さでは
// 目立たせず、代わりに破線（line-dasharray）にして区別する（HIGHWAY_DASHARRAY_*参照）。
const HIGHWAY_LINE_WIDTH_ARTERIAL = 6;
const HIGHWAY_LINE_WIDTH_SECONDARY = 4.5;
const HIGHWAY_LINE_WIDTH_LOCAL = 3;
const HIGHWAY_LINE_WIDTH_CYCLEWAY = 1.75;
const HIGHWAY_LINE_WIDTH_TRACK = 1.75;
const HIGHWAY_LINE_WIDTH_UNKNOWN = HIGHWAY_LINE_WIDTH_LOCAL;

// line-dasharrayは[on, off]をline-width単位で繰り返す。既知カテゴリは実線（[1, 0]=
// 途切れなし）、不明・他だけ破線にする。値を大きくするほど1つ1つの破線が長くなる。
const HIGHWAY_DASHARRAY_SOLID = [1, 0];
const HIGHWAY_DASHARRAY_UNKNOWN = [2, 1.5];

// OSMのhighwayタグ（道路種別）の表示用グルーピング。
const HIGHWAY_GROUPS: CategoryGroup[] = [
  {
    key: "arterial",
    label: "幹線道路",
    color: COLOR_BAD,
    width: HIGHWAY_LINE_WIDTH_ARTERIAL,
    values: ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"],
  },
  {
    key: "secondary",
    label: "主要道",
    color: COLOR_AMBER,
    width: HIGHWAY_LINE_WIDTH_SECONDARY,
    values: ["secondary", "secondary_link", "tertiary", "tertiary_link"],
  },
  {
    key: "local",
    label: "生活道路",
    color: COLOR_SKY,
    width: HIGHWAY_LINE_WIDTH_LOCAL,
    values: ["residential", "unclassified", "living_street", "service", "road"],
  },
  {
    key: "cycleway",
    label: "自転車・歩行者道",
    color: COLOR_GOOD,
    width: HIGHWAY_LINE_WIDTH_CYCLEWAY,
    values: ["cycleway", "path", "footway", "pedestrian", "bridleway", "steps"],
  },
  {
    key: "track",
    label: "農道・林道",
    color: COLOR_BROWN,
    width: HIGHWAY_LINE_WIDTH_TRACK,
    values: ["track"],
  },
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

// buildMatchExpressionの太さ版。fallbackWidthは未知タグ時（プロパティ欠落・カテゴリ外）の太さ。
function buildWidthMatchExpression(field: string, groups: CategoryGroup[], fallbackWidth: number): unknown[] {
  const expression: unknown[] = ["match", matchInput(field)];
  for (const group of groups) {
    expression.push(group.values, group.width ?? fallbackWidth);
  }
  expression.push(fallbackWidth);
  return expression;
}

// buildMatchExpressionの線種版。既知カテゴリは実線、未知タグ（プロパティ欠落・カテゴリ外）
// だけ破線にする（「不明・他」を太さでなく線種で目立たせて区別するため）。
// matchの出力に生の配列（[1, 0]等）をそのまま渡すと、MapLibreがそれを「式」として解釈しようと
// して1つ目の要素を演算子名（文字列）として期待し、数値だと
// 「Expression name must be a string, but found number instead.」で addLayer 自体が失敗する
// （エラーはmap.on("error")経由でしか分からず、例外にはならないため見つけにくい）。
// ["literal", [...]] で包み、リテラル値として扱わせる必要がある。
function buildDashArrayExpression(field: string, groups: CategoryGroup[]): unknown[] {
  const allValues = groups.flatMap((group) => group.values);
  return [
    "match",
    matchInput(field),
    allValues,
    ["literal", HIGHWAY_DASHARRAY_SOLID],
    ["literal", HIGHWAY_DASHARRAY_UNKNOWN],
  ];
}

// unknownWidth/unknownDashedを渡すと「不明・他」エントリにもそれぞれ持たせる
// （太さ・線種で地図に反映する軸のみ）。
function buildGroupLegend(
  field: string,
  groups: CategoryGroup[],
  unknownWidth?: number,
  unknownDashed?: boolean
): LegendEntry[] {
  const allValues = groups.flatMap((group) => group.values);
  return [
    ...groups.map(({ key, color, label, values, width }) => ({
      key,
      color,
      label,
      filter: ["match", matchInput(field), values, true, false],
      ...(width !== undefined ? { width } : {}),
    })),
    {
      key: "unknown",
      color: COLOR_UNKNOWN,
      label: "不明・他",
      // どの既知カテゴリのタグ値にも一致しない（タグ無し含む）ものがフォールバック
      filter: ["match", matchInput(field), allValues, false, true],
      ...(unknownWidth !== undefined ? { width: unknownWidth } : {}),
      ...(unknownDashed ? { dashed: true } : {}),
    },
  ];
}

export const ROAD_FILTER_AXES: RoadFilterAxis[] = [
  {
    id: "surface",
    label: "路面の種類",
    legend: buildGroupLegend("surface", SURFACE_GROUPS),
    colorExpression: buildMatchExpression("surface", SURFACE_GROUPS),
  },
  {
    id: "highway",
    label: "道路の種類",
    legend: buildGroupLegend("highway", HIGHWAY_GROUPS, HIGHWAY_LINE_WIDTH_UNKNOWN, true),
    colorExpression: buildMatchExpression("highway", HIGHWAY_GROUPS),
    widthExpression: buildWidthMatchExpression("highway", HIGHWAY_GROUPS, HIGHWAY_LINE_WIDTH_UNKNOWN),
    dashArrayExpression: buildDashArrayExpression("highway", HIGHWAY_GROUPS),
  },
];

// 地図の線色は常にこの軸（路面の種類）の配色を使う。
export const ROAD_LINE_COLOR_AXIS_ID: RoadFilterAxisId = "surface";

// 地図の線の太さは常にこの軸（道路の種類）のwidthExpressionを使う。
export const ROAD_LINE_WIDTH_AXIS_ID: RoadFilterAxisId = "highway";

// 地図の線種（実線/破線）は常にこの軸（道路の種類）のdashArrayExpressionを使う。
export const ROAD_LINE_DASH_AXIS_ID: RoadFilterAxisId = "highway";

export function getRoadFilterAxis(id: RoadFilterAxisId): RoadFilterAxis {
  return ROAD_FILTER_AXES.find((axis) => axis.id === id) ?? ROAD_FILTER_AXES[0];
}

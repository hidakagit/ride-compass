// 路面レイヤー（無方向・地域固定データ）の絞り込み軸の定義。
//
// タイル（バックエンドのMVT）にはsurface_good（3値の正準分類）・surface（正規化済み
// OSM生タグ）・highway（OSM道路種別）が焼き込まれているが、絞り込み軸として持つのは
// 互いに独立な軸（路面の種類=surfaceタグ、道路の種類=highwayタグ）だけ。surface_goodは
// 路面の種類と同じsurfaceタグを2値に粗く束ねただけのもの（backend/app/domain/road.pyの
// GOOD_OSM_SURFACE_TAGS/BAD_OSM_SURFACE_TAGSと、下のSURFACE_GROUPSの分類が同一の
// surfaceタグに基づく）で、独立した軸として絞り込む意味を持たない
// （「路面の種類=アスファルト」かつ「舗装/未舗装=未舗装」のような組み合わせは常に矛盾するか
// 冗長になる）。路面の種類・道路の種類の2つは実際のOSMタグとして独立しており（同じ道路が
// どんな路面材質にもどんな道路種別にもなりうる）、組み合わせて絞り込む意味がある。
// 舗装路だけ見たい場合は「路面の種類」で砂利・土のカテゴリを外せば同じ結果になるため、
// 機能的な欠落は無い。
//
// 地図の色分け（line-color）は「路面の種類」がONの間は常にその配色で固定する（自転車走行の
// 実用上、最も情報量が多い軸のため。路面の種類の色が道路の種類の色を上書きする形で、
// 両方ONでも色の奪い合いは起きない）。ユーザーが色分け軸を選ぶUIは持たない（絞り込みと
// 色の選択を同じ画面に同居させると、絞り込んだ結果1色しか出ない軸を選べてしまい
// 情報量ゼロになる、という混乱があったため）。
//
// **意味を運ぶのは色だけで、太さ・線種は情報を持たない**（全ての線レイヤー共通の規約）。
// 複数の軸を同時にONにしたときは、色を掛け合わせるのではなくMapLibreのline-offsetで平行な
// トラックへ分ける（MapView.tsx: applyRoadMaterialTrackOffsets）——1本の線へ複数の意味を
// 載せると、どちらの意味の色なのかが他レイヤーのON/OFFに依存して入れ替わる。
//
// 軸を増やすときは、タイルへプロパティを1つ足し、ROAD_FILTER_AXESへ軸定義を1つ足すだけで
// よい（RoadFilterDialogは軸のリストを汎用的にループして描画するため、UI側の変更は不要）。
// 追加する軸は必ず「他の軸と独立して決まる事実」であること（例のような粒度違いの再掲は
// 避ける）。

import { COLOR_UNKNOWN } from "./axisLayers";
import type { LegendEntry } from "./legendFilter";

export type RoadFilterAxisId = "surface" | "highway";

export interface RoadFilterAxis {
  /** この軸の絞り込みを出す地図チップ（`MapLayerId`）。UI側が軸idから引けるようにここで
   * 宣言する——画面側で軸を名指しして配線すると、軸を1つ足すたびに同じ形のブロックが
   * 増える（「軸定義を1つ足すだけでよい」が成り立たなくなる）。 */
  layerId: string;
  id: RoadFilterAxisId;
  /** 絞り込みパネルの見出しに出す名前（例:「路面の種類で絞り込み」） */
  label: string;
  legend: LegendEntry[];
  /** MapLibreのline-colorに渡すスタイル式。軸ごとに独立したレイヤーが自分の式だけを使う
   * （他の軸のON/OFFで色の意味が変わることはない）。 */
  colorExpression: unknown[];
  /** MapLibreのline-opacityに渡すスタイル式。「不明・他」（対象外）を目立たなくし、
   * 分類情報を持つ区間だけを浮き上がらせる（下記FALLBACK_LINE_OPACITY参照）。
   * colorExpressionと同じ「路面の種類ON時はそちら、OFF時は道路の種類側」の出し分けで使う。 */
  opacityExpression?: unknown[];
}

// ルート候補線（選択=青#2563eb・未選択=アンバー#f59e0b）と紛れにくいよう、青は使わず
// 生活道路には空色を当てる。
//
// 「路面の種類」（SURFACE_GROUPS）の色は自分のレイヤーのline-colorへ直接反映され、
// 凡例も同じcolor値を丸ドットで表示する。2次のramp軸
// （停止密度・事故密度等、axisLayers.ts: AXIS_RAMP_COLORSの緑〜赤の評価配色）
// と色相が重なると、1次（観測された事実）と2次（推定された評価）が地図上で混同される
// ため、評価色（緑・アンバー・オレンジ・赤の系統）を避けた中立色を使う（COLOR_SLATE/
// COLOR_KHAKI）。COLOR_UNKNOWNはaxisLayers.tsが正準定義を持つ（dedicatedWayValueLayer.tsと
// 同じくそちらからimportする、定数の片側import）。

// 1次の複数レイヤーを同時にONにしても、視覚的な重なりが何を意味するか読み取れなくなる
// ことを避けるため、「不明・他」（そのタグ値が無い/未分類の区間、路面では2〜3割・
// 自転車インフラではほぼ大半を占める）だけ大きく透明度を下げ、分類情報を持つ
// 区間だけが浮かび上がるようにする。staticAttributeLayers.ts（自転車インフラ）
// とも共有し、地図全体で「薄い＝対象外、濃い＝分類あり」という読み方を統一する。
export const FALLBACK_LINE_OPACITY = 0.15;
export const KNOWN_LINE_OPACITY = 0.8;

const COLOR_TEAL = "#0d9488";
const COLOR_VIOLET = "#7c3aed";
const COLOR_BROWN = "#92400e";
const COLOR_SLATE = "#64748b";
const COLOR_KHAKI = "#a3915f";

// HIGHWAY_GROUPS（道路の種類）専用のパレット。「幹線道路ほど強く目立つ」序列を、色相を
// 持たない濃淡（青みがかった中立トーン）で表す——順序はあるが良し悪しではないため、
// 色相ベースの評価配色（axisLayers.ts: AXIS_RAMP_COLORSの緑〜赤）とは別の視覚言語にして
// あり、2次の評価色と混同しない。COLOR_SLATE（路面の種類=アスファルトが
// 使用中）やCOLOR_UNKNOWN（不明・他）とも別の色値にし、それぞれの文脈で意味が食い違わない
// ようにする。
const COLOR_HIGHWAY_ARTERIAL = "#334155";
const COLOR_HIGHWAY_SECONDARY = "#475569";
const COLOR_HIGHWAY_LOCAL = "#94a3b8";
const COLOR_HIGHWAY_MINOR = "#cbd5e1";

export interface CategoryGroup {
  key: string;
  label: string;
  color: string;
  /** このカテゴリに含めるタグ値（タイル側で正規化済みの小文字） */
  values: string[];
}

// OSMのsurfaceタグの表示用グルーピング。タグ値はバックエンド側でlower/trim正規化済み。
//
// 語彙の正準はbackendのdomain/road.py（GOOD/BAD_OSM_SURFACE_TAGS）で、その内容は
// types/generated/surface-tags.json（backend/scripts/export_openapi.pyが書き出し）として
// このリポジトリへコミットされている。roadFilterAxes.test.tsが「表示グループの全タグ＝
// 正準分類済みタグ全体」「舗装系グループはgoodのみ・未舗装系はbadのみ」を検証するため、
// どちらか片方だけタグを増減するとテストが割れる。
// 「石畳・敷石」だけはgood（paving_stones/bricks）とbad（sett/cobblestone等）が混在する
// 意図的な中立グループ（材質としては同類のため。色も良し悪しを示さない紫にしてある）。
export const SURFACE_GROUPS: CategoryGroup[] = [
  { key: "asphalt", label: "アスファルト", color: COLOR_SLATE, values: ["asphalt", "paved", "chipseal"] },
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
    color: COLOR_KHAKI,
    values: ["gravel", "fine_gravel", "compacted", "pebblestone", "rock"],
  },
  {
    key: "dirt",
    label: "土・草・砂",
    color: COLOR_BROWN,
    values: ["unpaved", "dirt", "ground", "earth", "mud", "sand", "grass", "woodchips"],
  },
];

// OSMのhighwayタグ（道路種別）の表示用グルーピング（地図の色分け・線幅専用、意図的に
// 多対一）。地図表示と評価で必要な粒度が異なる（軸スタジオは1値1ラベルが必要）ため、
// 軸スタジオの値ラベルはbackend/app/domain/material_catalog.py: MaterialSpec.value_labels
// から独立して導出する（「地図表示と評価は別」の方針）。このexportは地図の絞り込みUI
// 専用として維持する。
export const HIGHWAY_GROUPS: CategoryGroup[] = [
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
  {
    key: "track",
    label: "農道・林道",
    // 自転車・歩行者道と濃淡が近く見分けが付きにくいため、COLOR_HIGHWAY_MINORをそのまま
    // 使わず、SURFACE_GROUPSの「土・草・砂」
    // （dirt）と同じCOLOR_BROWNを流用する（別レイヤー・別トラックへ分かれて描かれるため
    // 画面上で直接競合せず、テーマ的にも未舗装路のイメージが重なり自然）。
    color: COLOR_BROWN,
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

// buildMatchExpressionの不透明度版。カテゴリの色に関わらず、分類済み（既知タグ）は
// KNOWN_LINE_OPACITY、「不明・他」はFALLBACK_LINE_OPACITYの一律2値にする（カテゴリごとの
// 濃淡は付けない。「分類できているか否か」だけを不透明度で示す）。
function buildOpacityMatchExpression(field: string, groups: CategoryGroup[]): unknown[] {
  const allValues = groups.flatMap((group) => group.values);
  return ["match", matchInput(field), allValues, KNOWN_LINE_OPACITY, FALLBACK_LINE_OPACITY];
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

export const ROAD_FILTER_AXES: RoadFilterAxis[] = [
  {
    id: "surface",
    layerId: "roadSurface",
    label: "路面の種類",
    legend: buildGroupLegend("surface", SURFACE_GROUPS),
    colorExpression: buildMatchExpression("surface", SURFACE_GROUPS),
    opacityExpression: buildOpacityMatchExpression("surface", SURFACE_GROUPS),
  },
  {
    id: "highway",
    layerId: "roadType",
    label: "道路の種類",
    legend: buildGroupLegend("highway", HIGHWAY_GROUPS),
    colorExpression: buildMatchExpression("highway", HIGHWAY_GROUPS),
    opacityExpression: buildOpacityMatchExpression("highway", HIGHWAY_GROUPS),
  },
];

// 軸ごとに1枚のレイヤーを持ち、そのレイヤーの色はこの軸の配色だけで決まる。
export const ROAD_SURFACE_AXIS_ID: RoadFilterAxisId = "surface";
export const ROAD_TYPE_AXIS_ID: RoadFilterAxisId = "highway";

export function getRoadFilterAxis(id: RoadFilterAxisId): RoadFilterAxis {
  return ROAD_FILTER_AXES.find((axis) => axis.id === id) ?? ROAD_FILTER_AXES[0];
}

// 静的道路属性 P0（docs/static-road-attributes-plan.md）の新規レイヤー
// （交通ストレス・自転車インフラ）、T54（既取込データの可視化漏れ解消）の
// 停止要因POI・交差点密度レイヤー、外部静的データソース T50（警察庁交通事故統計）の
// 色分け定義。
//
// roadFilterAxes.tsの軸機構（複数の生タグ値を少数のグループへ束ねる、絞り込み可能・
// 「路面」レイヤーの色分け軸として共有）とは異なり、これらはバックエンドが既に
// 1つの分類値（traffic_stress=1-4の整数、bicycle_infra/kind=列挙文字列、
// involves_bicycle/fatal=真偽値）へ変換済みのプロパティのため、生値→グループの
// 対応表は不要で単純なmatch/case式で足りる。
// 交通ストレス・自転車インフラは既存の「路面」レイヤー（ROAD_TILE_SOURCE_ID/
// ROAD_TILE_SOURCE_LAYERを共有）と同じソースの独立レイヤーだが、停止要因POI・交差点密度
// （region-poi-tiles）・事故（region-accident-tiles）は点データのためそれぞれ別ソース
// （MapView.tsx参照）になる。
// いずれも絞り込みUIは持たず色分け表示のみ（将来必要になればroadFilterAxes.ts側の機構への
// 統合を検討）。

import type { LegendEntry } from "./legendFilter";

const COLOR_UNKNOWN = "#9ca3af";

// LTS(Level of Traffic Stress)風の1-4段階。1=快適(緑)〜4=ストレス大(赤)。
// backend/app/domain/traffic.py: traffic_stress_levelと同じ意味論（1-4の整数、算出不能はNone）。
const TRAFFIC_STRESS_COLORS: Record<number, string> = {
  1: "#16a34a",
  2: "#84cc16",
  3: "#f59e0b",
  4: "#dc2626",
};

export const TRAFFIC_STRESS_LEGEND: LegendEntry[] = [
  { key: "1", label: "1（快適）", color: TRAFFIC_STRESS_COLORS[1], filter: ["==", ["get", "traffic_stress"], 1] },
  { key: "2", label: "2（やや快適）", color: TRAFFIC_STRESS_COLORS[2], filter: ["==", ["get", "traffic_stress"], 2] },
  { key: "3", label: "3（やや注意）", color: TRAFFIC_STRESS_COLORS[3], filter: ["==", ["get", "traffic_stress"], 3] },
  { key: "4", label: "4（ストレス大）", color: TRAFFIC_STRESS_COLORS[4], filter: ["==", ["get", "traffic_stress"], 4] },
  { key: "unknown", label: "不明・他", color: COLOR_UNKNOWN, filter: ["!", ["has", "traffic_stress"]] },
];

// プロパティ欠落時は-1へ倒し、どのケースにも一致しないようにする（["get",...]がnullのまま
// matchへ渡すと入力型不一致の評価エラーになりうるため、roadFilterAxes.tsのcoalesceパターンと
// 同じ考え方）。
export const TRAFFIC_STRESS_COLOR_EXPRESSION: unknown[] = [
  "match",
  ["coalesce", ["get", "traffic_stress"], -1],
  1,
  TRAFFIC_STRESS_COLORS[1],
  2,
  TRAFFIC_STRESS_COLORS[2],
  3,
  TRAFFIC_STRESS_COLORS[3],
  4,
  TRAFFIC_STRESS_COLORS[4],
  COLOR_UNKNOWN,
];

interface BicycleInfraCategory {
  key: string;
  label: string;
  color: string;
}

// backend/app/domain/traffic.py: classify_bicycle_infrastructureの列挙値と1:1対応
// （separated/lane/shared_busway/shared_pedestrian/roadway/prohibited、算出不能はunknown）。
//
// shared_pedestrianのラベル「歩道（自転車通行可）」は、roadFilterAxes.tsの「道路の種類」軸
// にあるhighway分類グループ「自転車・歩行者道」（highway=cycleway/path/footway/pedestrian/
// bridleway/steps）とは別概念（前者=自転車の通行条件、後者=道路種別タグ）だが、
// 中黒の有無だけの表記だと紛らわしいため区別できる書き方にしてある（改善計画T62）。
// 包含関係もきれいではない: highway=cycleway⊂separatedだが、path/footwayはbicycleタグ
// 次第でshared_pedestrianになる場合とroadwayに落ちる場合があり、pedestrian/bridleway/
// stepsはどちらの個別分岐も無くroadwayへ落ちる。cycleway=track併設の幹線道路は
// highway側では「自転車・歩行者道」に入らないままseparatedになる（非対称）。
const BICYCLE_INFRA_CATEGORIES: BicycleInfraCategory[] = [
  { key: "separated", label: "分離自転車道", color: "#16a34a" },
  { key: "lane", label: "自転車レーン", color: "#0d9488" },
  { key: "shared_busway", label: "バス専用道等の共用", color: "#d97706" },
  { key: "shared_pedestrian", label: "歩道（自転車通行可）", color: "#0284c7" },
  { key: "roadway", label: "車道（専用施設なし）", color: "#7c3aed" },
  { key: "prohibited", label: "自転車通行不可", color: "#dc2626" },
];

// key→labelの対訳表。MapView.tsxのポップアップ表示が参照する（改善計画T46。以前は
// MapView.tsx内に同じ6件を手作業で複製しており、この配列とのドリフト検知テストが
// 無かった。UI語彙表はカタログファイルにのみ書く、という方針の具体化）。
export const BICYCLE_INFRA_LABELS: Record<string, string> = Object.fromEntries(
  BICYCLE_INFRA_CATEGORIES.map((c) => [c.key, c.label]),
);

export const BICYCLE_INFRA_LEGEND: LegendEntry[] = [
  ...BICYCLE_INFRA_CATEGORIES.map((c) => ({
    key: c.key,
    label: c.label,
    color: c.color,
    filter: ["==", ["get", "bicycle_infra"], c.key],
  })),
  { key: "unknown", label: "不明・他", color: COLOR_UNKNOWN, filter: ["!", ["has", "bicycle_infra"]] },
];

export const BICYCLE_INFRA_COLOR_EXPRESSION: unknown[] = [
  "match",
  ["coalesce", ["get", "bicycle_infra"], ""],
  ...BICYCLE_INFRA_CATEGORIES.flatMap((c) => [c.key, c.color]),
  COLOR_UNKNOWN,
];

// 外部静的データソース T50（警察庁交通事故統計）の色分け定義。
// backend/app/domain/accident.py: involves_bicycle/is_fatalと同じ意味論
// （involves_bicycle=自転車が当事者A/Bのいずれかに該当、fatal=死者数>0）。
const ACCIDENT_COLOR_BICYCLE = "#dc2626";
const ACCIDENT_COLOR_OTHER = "#6b7280";

export const ACCIDENT_LEGEND: LegendEntry[] = [
  {
    key: "bicycle",
    label: "自転車関連",
    color: ACCIDENT_COLOR_BICYCLE,
    filter: ["==", ["get", "involves_bicycle"], true],
  },
  { key: "other", label: "その他", color: ACCIDENT_COLOR_OTHER, filter: ["==", ["get", "involves_bicycle"], false] },
];

export const ACCIDENT_COLOR_EXPRESSION: unknown[] = [
  "case",
  ["==", ["get", "involves_bicycle"], true],
  ACCIDENT_COLOR_BICYCLE,
  ACCIDENT_COLOR_OTHER,
];

// 死亡事故（fatal=true）は円を大きくして目立たせる（色は自転車関連/その他の軸を維持したまま強調）。
export const ACCIDENT_RADIUS_EXPRESSION: unknown[] = ["case", ["==", ["get", "fatal"], true], 6, 3];

// 改善計画T54（既取込データの可視化漏れ解消）: 停止要因POI（信号・横断歩道・一時停止・踏切）。
// osm_raw_pois（静的道路属性P1で取込済み）は評価（停止密度軸）にのみ使われ地図表示が
// 無かったため、新規に色分け表示する。backend/app/domain/traffic.py: StopPoiKindの
// 5値（traffic_signals/crossing/stop/give_way/level_crossing）と1:1対応。
interface StopPoiCategory {
  key: string;
  label: string;
  color: string;
}

const STOP_POI_CATEGORIES: StopPoiCategory[] = [
  { key: "traffic_signals", label: "信号", color: "#dc2626" },
  { key: "crossing", label: "横断歩道", color: "#2563eb" },
  { key: "stop", label: "一時停止", color: "#d97706" },
  { key: "give_way", label: "徐行", color: "#ca8a04" },
  { key: "level_crossing", label: "踏切", color: "#7c3aed" },
];

export const STOP_POI_LABELS: Record<string, string> = Object.fromEntries(
  STOP_POI_CATEGORIES.map((c) => [c.key, c.label]),
);

export const STOP_POI_LEGEND: LegendEntry[] = [
  ...STOP_POI_CATEGORIES.map((c) => ({
    key: c.key,
    label: c.label,
    color: c.color,
    filter: ["==", ["get", "kind"], c.key],
  })),
  // osm_raw_pois.kindは取込時にclassify_stop_poiで5値のいずれかへ分類済みのため実際には
  // 出現しない想定だが、match式のフォールバック（COLOR_UNKNOWN）と対にして凡例側にも残す
  // （trafficStress/bicycleInfraと同じ「不明・他」の扱い）。
  { key: "unknown", label: "不明・他", color: COLOR_UNKNOWN, filter: ["!", ["has", "kind"]] },
];

export const STOP_POI_COLOR_EXPRESSION: unknown[] = [
  "match",
  ["coalesce", ["get", "kind"], ""],
  ...STOP_POI_CATEGORIES.flatMap((c) => [c.key, c.color]),
  COLOR_UNKNOWN,
];

// 改善計画T54: 交差点密度（次数3以上のroad_node、backend/app/domain/traffic.py:
// INTERSECTION_DEGREE_THRESHOLD）。kindのようなカテゴリ分類ではなく単一種別のため、
// 凡例は1エントリのみ。次数（degree）が高いノードほど円を大きくし、「密度」を視覚化する。
export const INTERSECTION_COLOR = "#0f766e";

export const INTERSECTION_LEGEND: LegendEntry[] = [
  { key: "intersection", label: "交差点（接続路3本以上）", color: INTERSECTION_COLOR, filter: ["has", "degree"] },
];

// degree=3で半径4px、6以上で半径9pxまで線形補間する（それ以上の次数は稀なため頭打ちにする）。
export const INTERSECTION_RADIUS_EXPRESSION: unknown[] = [
  "interpolate",
  ["linear"],
  ["coalesce", ["get", "degree"], 3],
  3,
  4,
  6,
  9,
];

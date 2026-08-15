// 静的道路属性 P0（docs/static-road-attributes-plan.md）の新規レイヤー
// （交通ストレス・自転車インフラ）の色分け定義。
//
// roadFilterAxes.tsの軸機構（複数の生タグ値を少数のグループへ束ねる、絞り込み可能・
// 「路面」レイヤーの色分け軸として共有）とは異なり、これらはバックエンドが既に
// 1つの分類値（traffic_stress=1-4の整数、bicycle_infra=列挙文字列）へ変換済みの
// プロパティのため、生値→グループの対応表は不要で単純なmatch式で足りる。
// 独立した2つのMapLibreレイヤー（ROAD_TILE_SOURCE_ID/ROAD_TILE_SOURCE_LAYERを共有）として
// 表示し、既存の「路面」レイヤー（色分け軸固定）とは別にON/OFFする（P0時点では絞り込み
// UIは持たず、色分け表示のみ。将来必要になればroadFilterAxes.ts側の機構への統合を検討）。

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
const BICYCLE_INFRA_CATEGORIES: BicycleInfraCategory[] = [
  { key: "separated", label: "分離自転車道", color: "#16a34a" },
  { key: "lane", label: "自転車レーン", color: "#0d9488" },
  { key: "shared_busway", label: "バス専用道等の共用", color: "#d97706" },
  { key: "shared_pedestrian", label: "自転車歩行者道", color: "#0284c7" },
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

// 静的道路属性 P0（docs/static-road-attributes-plan.md）の新規レイヤー
// （交通ストレス・自転車インフラ）、T54（既取込データの可視化漏れ解消）の
// 停止要因POIレイヤー（交差点密度は同時に追加したがT96で地図可視化を撤去済み）、
// 外部静的データソース T50（警察庁交通事故統計）の色分け定義。
//
// roadFilterAxes.tsの軸機構（複数の生タグ値を少数のグループへ束ねる、絞り込み可能・
// 「路面」レイヤーの色分け軸として共有）とは異なり、これらはバックエンドが既に
// 1つの分類値（traffic_stress=1-5の整数、bicycle_infra/kind=列挙文字列、
// involves_bicycle/fatal=真偽値）へ変換済みのプロパティのため、生値→グループの
// 対応表は不要で単純なmatch/case式で足りる。
// 交通ストレス・自転車インフラは既存の「路面」レイヤー（ROAD_TILE_SOURCE_ID/
// ROAD_TILE_SOURCE_LAYERを共有）と同じソースの独立レイヤーだが、停止要因POI
// （region-poi-tiles）・事故（region-accident-tiles）は点データのためそれぞれ別ソース
// （MapView.tsx参照）になる。交差点密度（次数3以上のroad_node）はバックエンドの
// poi-tilesが引き続き焼き込むが、道路網を見れば概ね自明という判断で地図上の独立可視化
// レイヤーとしては提供しない（ルーティング材料のintersection_weightとしては引き続き使う）。
// 改善計画T63: 各レイヤーの絞り込みはSTATIC_FILTER_AXES（ファイル末尾）にカタログ化し、
// legendFilter.tsの汎用機構（roadFilterAxes.tsの「路面」レイヤーと同じbuildLegendFilterExpression/
// buildCombinedLegendFilterExpression）をそのまま流用する。属性値のカテゴリをそのまま絞り込み軸に
// 機械的展開するのではなく、レイヤーごとにアプリの目的（安全・快適なルート判断）に沿った軸を選ぶ:
// - 交通ストレス・自転車インフラ・停止要因POIは名義尺度（カテゴリに順序が無い）なので、個別カテゴリを
//   直接選べるカテゴリ絞り込みがそのまま「車道混在の区間だけ」「踏切だけ」等のニーズに合う。
// - 事故は当事者（自転車関連/その他）に加え、既に円の拡大で強調している重大度（死亡事故か否か）を
//   独立した第2軸として持たせ、道路情報の「路面の種類×道路の種類」と同じAND絞り込みで
//   「死亡事故だけ確認したい」に応える。

import type { LegendEntry } from "./legendFilter";
import type { MapLayerId } from "./mapLayers";
import { DEFAULT_SAFETY_RECIPE, buildSafetyExpression, type SafetyRecipe } from "./safetyExpression";
import {
  DEFAULT_TRAFFIC_STRESS_RECIPE,
  buildTrafficStressExpression,
  type TrafficStressRecipe,
} from "./trafficStressExpression";

const COLOR_UNKNOWN = "#9ca3af";

export interface CategoryDef {
  key: string;
  label: string;
  color: string;
}

// 「文字列列挙プロパティ→(label対訳表・凡例・match色分け式)の3点セット」の共通ビルダー
// （改善計画T82）。BICYCLE_INFRA/DESIGNATION/STOP_POIの3組が同じ骨格
// （Object.fromEntries変換・["=="]フィルタ＋unknown用["!","has"]フォールバック・
// ["match", ["coalesce",...]]色分け式）を逐語コピーしていたのを1箇所へ集約する。
// TRAFFIC_STRESS（数値キー）・ACCIDENT（当事者/重大度の2値をcase式で直接書く方が
// 自然）は同型でないため対象外。
function buildCategoricalLayerDefs(
  property: string,
  categories: readonly CategoryDef[],
  unknownLabel: string,
): { labels: Record<string, string>; legend: LegendEntry[]; colorExpression: unknown[] } {
  const labels = Object.fromEntries(categories.map((c) => [c.key, c.label]));
  const legend: LegendEntry[] = [
    ...categories.map((c) => ({
      key: c.key,
      label: c.label,
      color: c.color,
      filter: ["==", ["get", property], c.key],
    })),
    {
      key: "unknown",
      label: unknownLabel,
      color: COLOR_UNKNOWN,
      filter: ["!", ["has", property]],
      isFallback: true,
    },
  ];
  const colorExpression: unknown[] = [
    "match",
    ["coalesce", ["get", property], ""],
    ...categories.flatMap((c) => [c.key, c.color]),
    COLOR_UNKNOWN,
  ];
  return { labels, legend, colorExpression };
}

// LTS(Level of Traffic Stress)風の1-5段階。1=快適(緑)〜5=ストレス大(赤)。
// backend/app/domain/traffic.py: traffic_stress_levelと同じ意味論（1-5の整数、算出不能はNone）。
// exportしているのはTrafficStressRecipePanel（改善計画: レシピ入力フォームの改善）が
// 基準値の選択UI（低→高のレベルピッカー）の色・段階数をここから導出し、地図の色分けと
// 常に一致させるため。段階数をさらに増やす場合もここへキーを追加するだけで両方に反映される。
// 改善計画（交通ストレス5段階化）: 実データ実測で旧上限4にraw値5〜7が丸め込まれ、
// primary/trunk/指定路線（N10/N12）の悪化要因が地図上で見分けられなくなっていたため
// 4→5へ拡張した。旧レベル4の色（赤）は新レベル5（最悪）へ引き継ぎ、新レベル4には
// 中間色（オレンジ）を割り当てた。
export const TRAFFIC_STRESS_COLORS: Record<number, string> = {
  1: "#16a34a",
  2: "#84cc16",
  3: "#f59e0b",
  4: "#f97316",
  5: "#dc2626",
};

// 交通ストレスの最終値は（改善計画: 交通ストレスレシピ外出し基盤により）タイルへ計算済みの
// 値として焼き込まれておらず、材料タグ（highway/cycleway_class/maxspeed_kmh/lanes_count/
// designation/motor_vehicle_no）からMapLibre expressionとして計算する
// （trafficStressExpression.ts参照）。レシピ（研究モードで上書き可能、改善計画:
// 交通ストレスレシピ調整UIパネル）ごとに凡例・色分け式が変わるため関数化してある。
// 既定レシピ（DEFAULT_TRAFFIC_STRESS_RECIPE）を渡す限り見た目は従来と同一。

// 「不明・他」が1〜5と並ぶ6番目の数値段階に見え「1〜6評価」と誤解されるという実機
// フィードバック（改善計画T89）を受け、isFallback: trueを立てて描画側（MapLayersPanel・
// MapOverlayControls）に区切り線＋弱調表示させる。
export function buildTrafficStressLegend(
  recipe: TrafficStressRecipe,
  levelExpression: unknown[] = buildTrafficStressExpression(recipe),
): LegendEntry[] {
  return [
    { key: "1", label: "1[快適]", color: TRAFFIC_STRESS_COLORS[1], filter: ["==", levelExpression, 1] },
    { key: "2", label: "2[やや快適]", color: TRAFFIC_STRESS_COLORS[2], filter: ["==", levelExpression, 2] },
    { key: "3", label: "3[やや注意]", color: TRAFFIC_STRESS_COLORS[3], filter: ["==", levelExpression, 3] },
    { key: "4", label: "4[注意]", color: TRAFFIC_STRESS_COLORS[4], filter: ["==", levelExpression, 4] },
    { key: "5", label: "5[ストレス大]", color: TRAFFIC_STRESS_COLORS[5], filter: ["==", levelExpression, 5] },
    {
      key: "unknown",
      label: "不明・他[判定対象外の道路種別]",
      color: COLOR_UNKNOWN,
      filter: ["==", levelExpression, -1],
      isFallback: true,
    },
  ];
}

// buildTrafficStressExpressionは判定対象外を-1で返す（trafficStressExpression.ts参照）ため、
// 従来の`coalesce(get("traffic_stress"), -1)`と同じ形でmatchできる。
// levelExpressionを省略した場合はrecipeから自前で計算する（単体呼び出し・モジュール直下の
// TRAFFIC_STRESS_COLOR_EXPRESSION定数用）。呼び出し元がbuildTrafficStressLegendと同じ
// レシピで両方組み立てる場合は、二重計算を避けるため計算済みの式を渡すこと
// （MapView.tsx: setStaticOverlayFiltersを参照）。
export function buildTrafficStressColorExpression(
  recipe: TrafficStressRecipe,
  levelExpression: unknown[] = buildTrafficStressExpression(recipe),
): unknown[] {
  return [
    "match",
    levelExpression,
    1,
    TRAFFIC_STRESS_COLORS[1],
    2,
    TRAFFIC_STRESS_COLORS[2],
    3,
    TRAFFIC_STRESS_COLORS[3],
    4,
    TRAFFIC_STRESS_COLORS[4],
    5,
    TRAFFIC_STRESS_COLORS[5],
    COLOR_UNKNOWN,
  ];
}

export const TRAFFIC_STRESS_LEGEND: LegendEntry[] = buildTrafficStressLegend(DEFAULT_TRAFFIC_STRESS_RECIPE);

export const TRAFFIC_STRESS_COLOR_EXPRESSION: unknown[] = buildTrafficStressColorExpression(
  DEFAULT_TRAFFIC_STRESS_RECIPE,
);

// 安全度（1-4、客観的な事故・怪我リスク）の色分け定義（改善計画: 安全度レシピ）。
// TRAFFIC_STRESS_COLORSと同じ1-4段階の構造だが、快適性（交通ストレス）とは別概念のため
// 地図上で混同しないよう色相をずらす（緑〜赤ではなくteal→olive→orange→dark-redの配色）。
// SafetyRecipePanel（交通ストレスのStressLevelPickerと同じ発想）が基準値ピッカーの色・
// 段階数をここから導出し、地図の色分けと常に一致させる。
export const SAFETY_COLORS: Record<number, string> = {
  1: "#0d9488",
  2: "#65a30d",
  3: "#ea580c",
  4: "#991b1b",
};

// 安全度の最終値もタイルへ計算済みの値として焼き込まれておらず（改善計画: 安全度レシピ、
// 交通ストレスと同じ理由）、材料タグからMapLibre expressionとして計算する
// （safetyExpression.ts参照）。buildTrafficStressLegend/buildTrafficStressColorExpressionと
// 同じ構造。
export function buildSafetyLegend(
  recipe: SafetyRecipe,
  levelExpression: unknown[] = buildSafetyExpression(recipe),
): LegendEntry[] {
  return [
    { key: "1", label: "1[安全]", color: SAFETY_COLORS[1], filter: ["==", levelExpression, 1] },
    { key: "2", label: "2[やや安全]", color: SAFETY_COLORS[2], filter: ["==", levelExpression, 2] },
    { key: "3", label: "3[やや危険]", color: SAFETY_COLORS[3], filter: ["==", levelExpression, 3] },
    { key: "4", label: "4[危険]", color: SAFETY_COLORS[4], filter: ["==", levelExpression, 4] },
    {
      key: "unknown",
      label: "不明・他[判定対象外の道路種別]",
      color: COLOR_UNKNOWN,
      filter: ["==", levelExpression, -1],
      isFallback: true,
    },
  ];
}

export function buildSafetyColorExpression(
  recipe: SafetyRecipe,
  levelExpression: unknown[] = buildSafetyExpression(recipe),
): unknown[] {
  return [
    "match",
    levelExpression,
    1,
    SAFETY_COLORS[1],
    2,
    SAFETY_COLORS[2],
    3,
    SAFETY_COLORS[3],
    4,
    SAFETY_COLORS[4],
    COLOR_UNKNOWN,
  ];
}

export const SAFETY_LEGEND: LegendEntry[] = buildSafetyLegend(DEFAULT_SAFETY_RECIPE);

export const SAFETY_COLOR_EXPRESSION: unknown[] = buildSafetyColorExpression(DEFAULT_SAFETY_RECIPE);

// backend/app/domain/traffic.py: classify_bicycle_infrastructureの列挙値と1:1対応
// （separated/lane/shared_busway/shared_pedestrian/roadway/prohibited、算出不能はunknown）。
//
// shared_pedestrianのラベル「歩道[自転車通行可]」は、roadFilterAxes.tsの「道路の種類」軸
// にあるhighway分類グループ「自転車・歩行者道」（highway=cycleway/path/footway/pedestrian/
// bridleway/steps）とは別概念（前者=自転車の通行条件、後者=道路種別タグ）だが、
// 中黒の有無だけの表記だと紛らわしいため区別できる書き方にしてある（改善計画T62）。
// 包含関係もきれいではない: highway=cycleway⊂separatedだが、path/footwayはbicycleタグ
// 次第でshared_pedestrianになる場合とroadwayに落ちる場合があり、pedestrian/bridleway/
// stepsはどちらの個別分岐も無くroadwayへ落ちる。cycleway=track併設の幹線道路は
// highway側では「自転車・歩行者道」に入らないままseparatedになる（非対称）。
const BICYCLE_INFRA_CATEGORIES: CategoryDef[] = [
  { key: "separated", label: "分離自転車道", color: "#16a34a" },
  { key: "lane", label: "自転車レーン", color: "#0d9488" },
  { key: "shared_busway", label: "バス専用道等の共用", color: "#d97706" },
  { key: "shared_pedestrian", label: "歩道[自転車通行可]", color: "#0284c7" },
  { key: "roadway", label: "車道[専用施設なし]", color: "#7c3aed" },
  { key: "prohibited", label: "自転車通行不可", color: "#dc2626" },
];

const bicycleInfraDefs = buildCategoricalLayerDefs("bicycle_infra", BICYCLE_INFRA_CATEGORIES, "不明・他");

// key→labelの対訳表。MapView.tsxのポップアップ表示が参照する（改善計画T46。以前は
// MapView.tsx内に同じ6件を手作業で複製しており、この配列とのドリフト検知テストが
// 無かった。UI語彙表はカタログファイルにのみ書く、という方針の具体化）。
export const BICYCLE_INFRA_LABELS: Record<string, string> = bicycleInfraDefs.labels;
export const BICYCLE_INFRA_LEGEND: LegendEntry[] = bicycleInfraDefs.legend;
export const BICYCLE_INFRA_COLOR_EXPRESSION: unknown[] = bicycleInfraDefs.colorExpression;

// 指定路線コンフレーション機構（外部静的データソース T51、国土数値情報N10/N12）の色分け定義。
// backend/app/infrastructure/road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQLの
// designationプロパティ（emergency_transport/critical_logistics/both/未該当はプロパティ欠落）と
// 対応する。トラフィックストレス・自転車インフラと同じroad_surfaceソースの独立レイヤー。
// 改善計画T74: N10・N12両方に該当するwayは3値目"both"として独立カテゴリ化する
// （以前は単一値CASE式でemergency_transport側のみ出力され、凡例で「緊急輸送道路」を
// 非表示にするとN12でもある区間が地図から完全に消えていた）。
const DESIGNATION_CATEGORIES: CategoryDef[] = [
  { key: "emergency_transport", label: "緊急輸送道路[N10]", color: "#b91c1c" },
  { key: "critical_logistics", label: "重要物流道路[N12]", color: "#1d4ed8" },
  // 改善計画: 全角括弧（）は表示幅を取り地図表示エリアを圧迫するため半角[]へ統一
  // （設計原則12、docs/complexity-review-2026-08-16.md）。地図上の内訳パネル（幅が狭い）で
  // 見切れやすいという実機報告（モバイル）を機にT104で個別対応した後、システムUI全般の
  // 方針として明文化された。「緊急輸送道路 かつ 重要物流道路」は共有語「道路」の重複表現を
  // 割愛し「緊急輸送 かつ 重要物流道路」へ短縮（ユーザー指定の表記）。折り返し自体もCSS側で
  // 許可済み（MapOverlayControls.module.css: .detailRowLabel）。
  { key: "both", label: "緊急輸送 かつ 重要物流道路[N10＋N12]", color: "#7c3aed" },
];

const designationDefs = buildCategoricalLayerDefs("designation", DESIGNATION_CATEGORIES, "対象外");

// key→labelの対訳表。MapView.tsxのポップアップ表示が参照する（BICYCLE_INFRA_LABELSと同じ理由）。
export const DESIGNATION_LABELS: Record<string, string> = designationDefs.labels;
export const DESIGNATION_LEGEND: LegendEntry[] = designationDefs.legend;
export const DESIGNATION_COLOR_EXPRESSION: unknown[] = designationDefs.colorExpression;

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

// 事故の「重大度」絞り込み軸（改善計画T63）。当事者（自転車関連/その他、ACCIDENT_LEGEND）とは
// 独立した軸で、道路情報の路面の種類×道路の種類と同じAND絞り込み
// （legendFilter.ts: buildCombinedLegendFilterExpression）を適用する。死亡事故は既に円の拡大
// （ACCIDENT_RADIUS_EXPRESSION）で強調表示しているが、「死亡事故だけ確認したい」という安全確認の
// 目的に直接応えるため絞り込み単体としても選べるようにする。fatalはmigration 0006でNOT NULL
// （accident.py: is_fatalが常にbool値を返す）のため、ACCIDENT_LEGENDと異なり不明・他は無い。
const ACCIDENT_SEVERITY_COLOR_FATAL = "#dc2626";
const ACCIDENT_SEVERITY_COLOR_OTHER = "#9ca3af";

export const ACCIDENT_SEVERITY_LEGEND: LegendEntry[] = [
  { key: "fatal", label: "死亡事故", color: ACCIDENT_SEVERITY_COLOR_FATAL, filter: ["==", ["get", "fatal"], true] },
  {
    key: "nonfatal",
    label: "死亡事故以外",
    color: ACCIDENT_SEVERITY_COLOR_OTHER,
    filter: ["==", ["get", "fatal"], false],
  },
];

// 改善計画T54（既取込データの可視化漏れ解消）: 停止要因POI（信号・横断歩道・一時停止・踏切）。
// osm_raw_pois（静的道路属性P1で取込済み）は評価（停止密度軸）にのみ使われ地図表示が
// 無かったため、新規に色分け表示する。backend/app/domain/traffic.py: StopPoiKindの
// 5値（traffic_signals/crossing/stop/give_way/level_crossing）と1:1対応。
const STOP_POI_CATEGORIES: CategoryDef[] = [
  { key: "traffic_signals", label: "信号", color: "#dc2626" },
  { key: "crossing", label: "横断歩道", color: "#2563eb" },
  { key: "stop", label: "一時停止", color: "#d97706" },
  { key: "give_way", label: "徐行", color: "#ca8a04" },
  { key: "level_crossing", label: "踏切", color: "#7c3aed" },
];

// osm_raw_pois.kindは取込時にclassify_stop_poiで5値のいずれかへ分類済みのため実際には
// unknown（プロパティ欠落）は出現しない想定だが、match式のフォールバック（COLOR_UNKNOWN）
// と対にして凡例側にも残す（trafficStress/bicycleInfraと同じ「不明・他」の扱い）。
const stopPoiDefs = buildCategoricalLayerDefs("kind", STOP_POI_CATEGORIES, "不明・他");

export const STOP_POI_LABELS: Record<string, string> = stopPoiDefs.labels;
export const STOP_POI_LEGEND: LegendEntry[] = stopPoiDefs.legend;
export const STOP_POI_COLOR_EXPRESSION: unknown[] = stopPoiDefs.colorExpression;

// 改善計画T63: 絞り込みUIの生成に使う、絞り込み可能な各静的レイヤーの軸カタログ。
// 1レイヤーに複数軸を持つのは事故（当事者×重大度）のみ。layerIdはmapLayers.tsのMapLayerIdと
// 一致させ、チェック操作時にそのレイヤーを自動でONにする判定（MapLayersPanel.tsx）に使う。
export type StaticFilterAxisId =
  | "trafficStress"
  | "safety"
  | "bicycleInfra"
  | "designation"
  | "stopPoi"
  | "accidentParty"
  | "accidentSeverity";

export interface StaticFilterAxis {
  axisId: StaticFilterAxisId;
  layerId: MapLayerId;
  /** 絞り込みパネルの軸見出し。1レイヤー1軸なら省略（レイヤー名で足りるため）。 */
  label?: string;
  legend: readonly LegendEntry[];
}

export const STATIC_FILTER_AXES: readonly StaticFilterAxis[] = [
  { axisId: "trafficStress", layerId: "trafficStress", legend: TRAFFIC_STRESS_LEGEND },
  { axisId: "safety", layerId: "safety", legend: SAFETY_LEGEND },
  { axisId: "bicycleInfra", layerId: "bicycleInfra", legend: BICYCLE_INFRA_LEGEND },
  { axisId: "designation", layerId: "designation", legend: DESIGNATION_LEGEND },
  { axisId: "stopPoi", layerId: "stopPoi", legend: STOP_POI_LEGEND },
  { axisId: "accidentParty", layerId: "accidents", label: "当事者", legend: ACCIDENT_LEGEND },
  { axisId: "accidentSeverity", layerId: "accidents", label: "重大度", legend: ACCIDENT_SEVERITY_LEGEND },
];

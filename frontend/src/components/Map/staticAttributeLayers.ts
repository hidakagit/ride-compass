// 静的道路属性 P0（docs/static-road-attributes-plan.md）の新規レイヤー
// （車ストレス・自転車インフラ）、T54（既取込データの可視化漏れ解消）の
// 停止要因POIレイヤー（交差点密度は同時に追加したがT96で地図可視化を撤去済み）、
// 外部静的データソース T50（警察庁交通事故統計）の色分け定義。
//
// roadFilterAxes.tsの軸機構（複数の生タグ値を少数のグループへ束ねる、絞り込み可能・
// 「路面」レイヤーの色分け軸として共有）とは異なり、これらはバックエンドが既に
// 1つの分類値（car_stress=1-5の整数、bicycle_infra/kind=列挙文字列、
// involves_bicycle/fatal=真偽値）へ変換済みのプロパティのため、生値→グループの
// 対応表は不要で単純なmatch/case式で足りる。
// 車ストレス・自転車インフラは既存の「路面」レイヤー（ROAD_TILE_SOURCE_ID/
// ROAD_TILE_SOURCE_LAYERを共有）と同じソースの独立レイヤーだが、停止要因POI
// （region-poi-tiles）・事故（region-accident-tiles）は点データのためそれぞれ別ソース
// （MapView.tsx参照）になる。交差点密度（次数3以上のroad_node）はバックエンドの
// poi-tilesが引き続き焼き込むが、道路網を見れば概ね自明という判断で地図上の独立可視化
// レイヤーとしては提供しない（ルーティング材料のintersection_weightとしては引き続き使う）。
// 改善計画T63: 各レイヤーの絞り込みはSTATIC_FILTER_AXES（ファイル末尾）にカタログ化し、
// legendFilter.tsの汎用機構（roadFilterAxes.tsの「路面」レイヤーと同じbuildLegendFilterExpression/
// buildCombinedLegendFilterExpression）をそのまま流用する。属性値のカテゴリをそのまま絞り込み軸に
// 機械的展開するのではなく、レイヤーごとにアプリの目的（安全・快適なルート判断）に沿った軸を選ぶ:
// - 車ストレス・自転車インフラ・停止要因POIは名義尺度（カテゴリに順序が無い）なので、個別カテゴリを
//   直接選べるカテゴリ絞り込みがそのまま「車道混在の区間だけ」「踏切だけ」等のニーズに合う。
// - 事故は当事者（自転車関連/その他）に加え、既に円の拡大で強調している重大度（死亡事故か否か）を
//   独立した第2軸として持たせ、道路情報の「路面の種類×道路の種類」と同じAND絞り込みで
//   「死亡事故だけ確認したい」に応える。

import type { LegendEntry } from "./legendFilter";
import type { MapLayerId } from "./mapLayers";
import { AXIS_RAMP_COLORS, RAMP_AXES, axisMapLayerId, buildAxisRampLegend, type RampAxis } from "./axisLayers";
import { FALLBACK_LINE_OPACITY, KNOWN_LINE_OPACITY } from "./roadFilterAxes";
import {
  DEFAULT_CAR_STRESS_RECIPE,
  buildCarStressExpression,
  type CarStressRecipe,
} from "./carStressExpression";

const COLOR_UNKNOWN = "#9ca3af";

// 改善計画（1次/2次の地図上表現の統一、竹）: このファイルのカテゴリ色（自転車インフラ・
// 指定路線・停止要因POI・補給POI・事故当事者）は「観測された事実の種類」を区別する
// ためのもので、良し悪しの評価ではない。にもかかわらず緑（良い）・赤（悪い）・アンバー
// （警告）を種類ラベルとして流用しており、2次のramp軸（車の圧迫感・停止密度・事故密度等、
// axisLayers.ts: AXIS_RAMP_COLORSの緑〜赤の評価配色）や旧CAR_STRESS_COLORSと同系統の
// 色が「事実」と「評価」の両方で使われ、地図上で混同されるという実機フィードバックを
// 受けて中立色（藍・灰茶・桃など、評価配色に含まれない色相）へ差し替えた。各カテゴリ群
// （bicycleInfra/stopPoi/supplyPoi/accident）は互いに独立した凡例・レイヤーのため、
// 色の使い回しは問題にならない（同じ画面で並べて比較されることが無い）。
// 唯一の例外はACCIDENT_SEVERITY_COLOR_FATAL（死亡事故）で、これは「事実の種類」ではなく
// 実際に重大な事実そのものであるため、赤を維持している（下記コメント参照）。
const COLOR_NEUTRAL_INDIGO = "#4f46e5";
const COLOR_NEUTRAL_STONE = "#78716c";
const COLOR_NEUTRAL_PINK = "#be185d";
const COLOR_NEUTRAL_FUCHSIA = "#a21caf";
const COLOR_NEUTRAL_TEAL_DARK = "#0f766e";

export interface CategoryDef {
  key: string;
  label: string;
  color: string;
}

// 「文字列列挙プロパティ→(label対訳表・凡例・match色分け式)の3点セット」の共通ビルダー
// （改善計画T82）。BICYCLE_INFRA/DESIGNATION/STOP_POIの3組が同じ骨格
// （Object.fromEntries変換・["=="]フィルタ＋unknown用["!","has"]フォールバック・
// ["match", ["coalesce",...]]色分け式）を逐語コピーしていたのを1箇所へ集約する。
// CAR_STRESS（数値キー）・ACCIDENT（当事者/重大度の2値をcase式で直接書く方が
// 自然）は同型でないため対象外。
function buildCategoricalLayerDefs(
  property: string,
  categories: readonly CategoryDef[],
  unknownLabel: string,
): { labels: Record<string, string>; legend: LegendEntry[]; colorExpression: unknown[]; opacityExpression: unknown[] } {
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
  // 「不明・他」（該当タグ無し）を目立たなくし、分類情報を持つ区間だけを浮き上がらせる
  // （改善計画: 1次要素の複数同時表示、対象外区間の低不透明度化。roadFilterAxes.tsの
  // FALLBACK_LINE_OPACITY/KNOWN_LINE_OPACITYと共有し、地図全体で読み方を統一する）。
  const opacityExpression: unknown[] = [
    "match",
    ["coalesce", ["get", property], ""],
    ...categories.flatMap((c) => [c.key, KNOWN_LINE_OPACITY]),
    FALLBACK_LINE_OPACITY,
  ];
  return { labels, legend, colorExpression, opacityExpression };
}

// LTS(Level of Traffic Stress)風の1-5段階。1=快適(緑)〜5=ストレス大(赤)。
// backend/app/domain/traffic.py: car_stress_levelと同じ意味論（1-5の整数、算出不能はNone）。
// exportしているのはCarStressRecipePanel（改善計画: レシピ入力フォームの改善）が
// 基準値の選択UI（低→高のレベルピッカー）の色・段階数をここから導出し、地図の色分けと
// 常に一致させるため。段階数をさらに増やす場合もここへキーを追加するだけで両方に反映される。
// 改善計画（車ストレス5段階化）: 実データ実測で旧上限4にraw値5〜7が丸め込まれ、
// primary/trunk/指定路線（N10/N12）の悪化要因が地図上で見分けられなくなっていたため
// 4→5へ拡張した。
//
// 改善計画（1次/2次の地図上表現の統一、梅）: 以前は車ストレス単独のTailwind系配色
// （緑#16a34a〜赤#dc2626）を持っていたが、停止密度・事故密度等のramp軸（axisLayers.ts:
// AXIS_RAMP_COLORS、緑→橙→赤のMaterial系4色）と色相ファミリーが異なり、「推定グループの
// どの軸を開いても同じ読み方」になっていなかった（実機フィードバック「1次と2次の地図上
// 表現を一致させたい」）。1・3・4・5段階目はAXIS_RAMP_COLORSをそのまま再利用して色を
// 統一する。ただしAXIS_RAMP_COLORSは4色・車ストレスは5段階のため単純に4色へ圧縮すると
// 4と5が同色になり、5段階化した理由（上記コメント）そのものが再発してしまう。そのため
// 2段階目だけAXIS_RAMP_COLORS[0]→[1]の間を橋渡しする遷移色（Material Light Green 500）を
// 新規に挿入し、5段階の判別性を保ったまま同じ色系統でつなぐ。
export const CAR_STRESS_COLORS: Record<number, string> = {
  1: AXIS_RAMP_COLORS[0],
  2: "#8bc34a",
  3: AXIS_RAMP_COLORS[1],
  4: AXIS_RAMP_COLORS[2],
  5: AXIS_RAMP_COLORS[3],
};

// 車ストレスの最終値は（改善計画: 車ストレスレシピ外出し基盤により）タイルへ計算済みの
// 値として焼き込まれておらず、材料タグ（highway/cycleway_class/maxspeed_kmh/lanes_count/
// designation/motor_vehicle_no）からMapLibre expressionとして計算する
// （carStressExpression.ts参照）。レシピ（研究モードで上書き可能、改善計画:
// 車ストレスレシピ調整UIパネル）ごとに凡例・色分け式が変わるため関数化してある。
// 既定レシピ（DEFAULT_CAR_STRESS_RECIPE）を渡す限り見た目は従来と同一。

// 「不明・他」が1〜5と並ぶ6番目の数値段階に見え「1〜6評価」と誤解されるという実機
// フィードバック（改善計画T89）を受け、isFallback: trueを立てて描画側（MapLayersPanel・
// MapOverlayControls）に区切り線＋弱調表示させる。
export function buildCarStressLegend(
  recipe: CarStressRecipe,
  levelExpression: unknown[] = buildCarStressExpression(recipe),
): LegendEntry[] {
  return [
    { key: "1", label: "1[快適]", color: CAR_STRESS_COLORS[1], filter: ["==", levelExpression, 1] },
    { key: "2", label: "2[やや快適]", color: CAR_STRESS_COLORS[2], filter: ["==", levelExpression, 2] },
    { key: "3", label: "3[やや注意]", color: CAR_STRESS_COLORS[3], filter: ["==", levelExpression, 3] },
    { key: "4", label: "4[注意]", color: CAR_STRESS_COLORS[4], filter: ["==", levelExpression, 4] },
    { key: "5", label: "5[圧迫大]", color: CAR_STRESS_COLORS[5], filter: ["==", levelExpression, 5] },
    {
      key: "unknown",
      label: "不明・他[判定対象外の道路種別]",
      color: COLOR_UNKNOWN,
      filter: ["==", levelExpression, -1],
      isFallback: true,
    },
  ];
}

// buildCarStressExpressionは判定対象外を-1で返す（carStressExpression.ts参照）ため、
// 従来の`coalesce(get("car_stress"), -1)`と同じ形でmatchできる。
// levelExpressionを省略した場合はrecipeから自前で計算する（単体呼び出し・モジュール直下の
// CAR_STRESS_COLOR_EXPRESSION定数用）。呼び出し元がbuildCarStressLegendと同じ
// レシピで両方組み立てる場合は、二重計算を避けるため計算済みの式を渡すこと
// （MapView.tsx: setStaticOverlayFiltersを参照）。
export function buildCarStressColorExpression(
  recipe: CarStressRecipe,
  levelExpression: unknown[] = buildCarStressExpression(recipe),
): unknown[] {
  return [
    "match",
    levelExpression,
    1,
    CAR_STRESS_COLORS[1],
    2,
    CAR_STRESS_COLORS[2],
    3,
    CAR_STRESS_COLORS[3],
    4,
    CAR_STRESS_COLORS[4],
    5,
    CAR_STRESS_COLORS[5],
    COLOR_UNKNOWN,
  ];
}

export const CAR_STRESS_LEGEND: LegendEntry[] = buildCarStressLegend(DEFAULT_CAR_STRESS_RECIPE);

export const CAR_STRESS_COLOR_EXPRESSION: unknown[] = buildCarStressColorExpression(
  DEFAULT_CAR_STRESS_RECIPE,
);

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
  { key: "separated", label: "分離自転車道", color: COLOR_NEUTRAL_INDIGO },
  { key: "lane", label: "自転車レーン", color: "#0d9488" },
  { key: "shared_busway", label: "バス専用道等の共用", color: COLOR_NEUTRAL_STONE },
  { key: "shared_pedestrian", label: "歩道[自転車通行可]", color: "#0284c7" },
  { key: "roadway", label: "車道[専用施設なし]", color: "#7c3aed" },
  { key: "prohibited", label: "自転車通行不可", color: COLOR_NEUTRAL_FUCHSIA },
];

const bicycleInfraDefs = buildCategoricalLayerDefs("bicycle_infra", BICYCLE_INFRA_CATEGORIES, "不明・他");

// key→labelの対訳表。MapView.tsxのポップアップ表示が参照する（改善計画T46。以前は
// MapView.tsx内に同じ6件を手作業で複製しており、この配列とのドリフト検知テストが
// 無かった。UI語彙表はカタログファイルにのみ書く、という方針の具体化）。
export const BICYCLE_INFRA_LABELS: Record<string, string> = bicycleInfraDefs.labels;
export const BICYCLE_INFRA_LEGEND: LegendEntry[] = bicycleInfraDefs.legend;
export const BICYCLE_INFRA_COLOR_EXPRESSION: unknown[] = bicycleInfraDefs.colorExpression;
export const BICYCLE_INFRA_OPACITY_EXPRESSION: unknown[] = bicycleInfraDefs.opacityExpression;

// 指定路線コンフレーション機構（外部静的データソース T51、国土数値情報N10/N12）の色分け定義。
// backend/app/infrastructure/road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQLの
// designationプロパティ（emergency_transport/critical_logistics/both/未該当はプロパティ欠落）と
// 対応する。トラフィックストレス・自転車インフラと同じroad_surfaceソースの独立レイヤー。
// 改善計画T74: N10・N12両方に該当するwayは3値目"both"として独立カテゴリ化する
// （以前は単一値CASE式でemergency_transport側のみ出力され、凡例で「緊急輸送道路」を
// 非表示にするとN12でもある区間が地図から完全に消えていた）。
const DESIGNATION_CATEGORIES: CategoryDef[] = [
  { key: "emergency_transport", label: "緊急輸送道路[N10]", color: COLOR_NEUTRAL_TEAL_DARK },
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
export const DESIGNATION_OPACITY_EXPRESSION: unknown[] = designationDefs.opacityExpression;

// 外部静的データソース T50（警察庁交通事故統計）の色分け定義。
// backend/app/domain/accident.py: involves_bicycle/is_fatalと同じ意味論
// （involves_bicycle=自転車が当事者A/Bのいずれかに該当、fatal=死者数>0）。
// 当事者（自転車関連/その他）は「事実の種類」の区別であり重大度ではないため、竹で
// 評価色の赤から中立色へ差し替えた。重大度（死亡事故か否か）は下のACCIDENT_SEVERITY_*
// を参照（そちらは赤を維持している）。
const ACCIDENT_COLOR_BICYCLE = COLOR_NEUTRAL_INDIGO;
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
// 竹（1次/2次の地図上表現の統一）でも赤を維持する唯一の例外。他のカテゴリ色（当事者・
// 停止要因種別等）は「事実の種類」を区別するラベルにすぎないが、死亡事故か否かは
// それ自体が重大な事実であり、赤＝危険という慣習的な読みが安全確認という目的に
// 直接寄与する（円の拡大ACCIDENT_RADIUS_EXPRESSIONと合わせて二重に強調する設計）。
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
  { key: "traffic_signals", label: "信号", color: COLOR_NEUTRAL_INDIGO },
  { key: "crossing", label: "横断歩道", color: "#2563eb" },
  { key: "stop", label: "一時停止", color: COLOR_NEUTRAL_STONE },
  { key: "give_way", label: "徐行", color: COLOR_NEUTRAL_PINK },
  { key: "level_crossing", label: "踏切", color: "#7c3aed" },
];

// osm_raw_pois.kindは取込時にclassify_stop_poiで5値のいずれかへ分類済みのため実際には
// unknown（プロパティ欠落）は出現しない想定だが、match式のフォールバック（COLOR_UNKNOWN）
// と対にして凡例側にも残す（carStress/bicycleInfraと同じ「不明・他」の扱い）。
const stopPoiDefs = buildCategoricalLayerDefs("kind", STOP_POI_CATEGORIES, "不明・他");

export const STOP_POI_LABELS: Record<string, string> = stopPoiDefs.labels;
export const STOP_POI_LEGEND: LegendEntry[] = stopPoiDefs.legend;
export const STOP_POI_COLOR_EXPRESSION: unknown[] = stopPoiDefs.colorExpression;

// 補給・休憩ポイントPOI（改善計画T101）の色分け定義。停止要因POIと同じ
// region-poi-tiles（source-layer: stop_poi）を共有する（MapView.tsx: POI_TILE_SOURCE_ID参照。
// バックエンドのMVT SQLはosm_raw_pois.kindを無条件で焼き込むため、2つの独立レイヤーの分離は
// フロント側のkind値によるフィルタで行う。STOP_POI_KINDS/SUPPLY_POI_KINDSをMapView.tsxの
// レイヤーfilterへ渡し、setStaticOverlayFiltersのbaseFilter（legendFilter.ts参照）で
// 互いの領域を侵さないようにする）。backend/app/domain/traffic.py: SupplyPoiKindの5値
// （convenience/vending_machine/toilets/drinking_water/bicycle_parking）と1:1対応。
const SUPPLY_POI_CATEGORIES: CategoryDef[] = [
  { key: "convenience", label: "コンビニ", color: COLOR_NEUTRAL_INDIGO },
  { key: "vending_machine", label: "自販機", color: "#0891b2" },
  { key: "toilets", label: "トイレ", color: "#2563eb" },
  { key: "drinking_water", label: "給水", color: "#0d9488" },
  { key: "bicycle_parking", label: "駐輪場", color: COLOR_NEUTRAL_STONE },
];

const supplyPoiDefs = buildCategoricalLayerDefs("kind", SUPPLY_POI_CATEGORIES, "不明・他");

export const SUPPLY_POI_LABELS: Record<string, string> = supplyPoiDefs.labels;
export const SUPPLY_POI_LEGEND: LegendEntry[] = supplyPoiDefs.legend;
export const SUPPLY_POI_COLOR_EXPRESSION: unknown[] = supplyPoiDefs.colorExpression;

// stopPoi/supplyPoiレイヤーのbaseFilter（上記参照）用、kind値の一覧。
export const STOP_POI_KINDS: readonly string[] = STOP_POI_CATEGORIES.map((c) => c.key);
export const SUPPLY_POI_KINDS: readonly string[] = SUPPLY_POI_CATEGORIES.map((c) => c.key);

// 改善計画T63: 絞り込みUIの生成に使う、絞り込み可能な各静的レイヤーの軸カタログ。
// 1レイヤーに複数軸を持つのは事故（当事者×重大度）のみ。layerIdはmapLayers.tsのMapLayerIdと
// 一致させ、チェック操作時にそのレイヤーを自動でONにする判定（MapLayersPanel.tsx）に使う。
// ramp軸（stop_density/accident等、axisLayers.ts参照）はaxis-catalog.json由来の動的なIDのため
// リテラル列挙できず、RampAxis["axisId"]（string）を足しあわせる（改善計画T145b: 停止/事故密度の
// 凡例追加。ここに追加のコード変更なしにSTATIC_FILTER_AXESへ含められる）。
export type StaticFilterAxisId =
  | "carStress"
  | "bicycleInfra"
  | "designation"
  | "stopPoi"
  | "supplyPoi"
  | "accidentParty"
  | "accidentSeverity"
  | RampAxis["axisId"];

export interface StaticFilterAxis {
  axisId: StaticFilterAxisId;
  layerId: MapLayerId;
  /** 絞り込みパネルの軸見出し。1レイヤー1軸なら省略（レイヤー名で足りるため）。 */
  label?: string;
  legend: readonly LegendEntry[];
  /** 凡例の非表示操作の有無に関わらず常にANDする恒常的な絞り込み（改善計画T101、
   * legendFilter.ts: buildCombinedLegendFilterExpressionのbaseFilter参照）。
   * stopPoi/supplyPoiが同じベクタタイルのkind値集合を分け合うためだけに使う特殊な軸のみ
   * 指定する（他の軸は不要＝undefinedで挙動不変）。 */
  baseFilter?: unknown[];
}

export const STATIC_FILTER_AXES: readonly StaticFilterAxis[] = [
  { axisId: "carStress", layerId: "carStress", legend: CAR_STRESS_LEGEND },
  { axisId: "bicycleInfra", layerId: "bicycleInfra", legend: BICYCLE_INFRA_LEGEND },
  { axisId: "designation", layerId: "designation", legend: DESIGNATION_LEGEND },
  {
    axisId: "stopPoi",
    layerId: "stopPoi",
    legend: STOP_POI_LEGEND,
    baseFilter: ["in", ["get", "kind"], ["literal", STOP_POI_KINDS]],
  },
  {
    axisId: "supplyPoi",
    layerId: "supplyPoi",
    legend: SUPPLY_POI_LEGEND,
    baseFilter: ["in", ["get", "kind"], ["literal", SUPPLY_POI_KINDS]],
  },
  { axisId: "accidentParty", layerId: "accidents", label: "当事者", legend: ACCIDENT_LEGEND },
  { axisId: "accidentSeverity", layerId: "accidents", label: "重大度", legend: ACCIDENT_SEVERITY_LEGEND },
  // ramp軸（停止密度・事故密度等）の凡例。凡例の内訳はカタログのthresholds/tile_inputsから
  // 自動生成される（axisLayers.ts: buildAxisRampLegend）ため、軸追加時にここへの変更は不要。
  ...RAMP_AXES.map((axis) => ({
    axisId: axis.axisId,
    layerId: axisMapLayerId(axis.axisId),
    legend: buildAxisRampLegend(axis),
  })),
];

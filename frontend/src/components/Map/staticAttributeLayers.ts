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

const COLOR_UNKNOWN = "#9ca3af";

// 改善計画（1次/2次の地図上表現の統一、竹→1次の点要素の順序付け）: このファイルの
// カテゴリ色は、対象によって2種類に分かれる。判定基準は「backendの2次軸の計算式が
// 実際にこのカテゴリを重み付けの材料として使っているか」（mapLayers.ts:
// panelHintDetail、または各domain/*.pyの集計ロジックで確認できる）で、UIの見た目だけで
// 決めない。
//
// (A) 純粋な分類（順序を持たない）: 停止要因POIの種別（信号/横断歩道/一時停止/徐行/踏切）は
// backend/app/infrastructure/road_graph_repository.pyのstop_per_km集計が全種別を等しく
// カウントしており（kind別の重み差なし）、補給POIの種類は非安全指標でどの2次軸の材料にも
// なっていない。どちらも「観測された事実の種類」を区別するだけで、どちらが強い/弱いという
// 順序を持たない。かつては緑（良い）・赤（悪い）・アンバー（警告）を種類ラベルとして
// 流用しており、2次のramp軸（車の圧迫感・停止密度・事故密度等、axisLayers.ts:
// AXIS_RAMP_COLORSの緑〜赤の評価配色）と紛らわしいだけでなく、「順序が無いものに順序が
// あるかのような嘘の意味」を作ってしまっていたため、評価配色を含まない中立色（藍・灰茶・
// 桃など）へ差し替えた。各カテゴリ群は互いに独立した凡例・レイヤーのため、色の使い回しは
// 問題にならない（同じ画面で並べて比較されることが無い）。
//
// (B) 2次の材料そのもの（順序を持つ）: 自転車インフラ・指定路線・事故の当事者区分
// （自転車関連/その他）は、実際に2次の計算材料として使われている（自転車インフラ・
// 指定路線は改善計画T292のcar_stress内部軸（domain/axis_definitions.py:
// car_stress_bicycle_infra_adjustment「分離自転車道: -2」等・
// car_stress_designation_adjustment「指定路線に該当: +1」）の材料。
// 事故の当事者区分はbackend/app/infrastructure/road_graph_repository.pyの
// 事故密度集計がbicycle_only=true固定＝自転車関連の事故だけを数え、その他は数えない
// ＝寄与ゼロ、domain/accident.py: distance_weighted_accident_density参照）。つまりこれらは
// 「安全寄り→危険寄り」という2次と同じ意味の順序を実際に持っており、中立色にしてしまうと
// 「濃ければ強い？」というだけの手がかりの無い色になってしまう（実機フィードバック
// 「1次の軸色の意味合いが読めない」「1次の点要素にも順序付けがあれば反映してほしい」）。
// これらは2次と同じ緑→赤の配色言語（AXIS_RAMP_COLORS系）へ揃え、「1次のこの色は2次の
// この色と同じ方向を指す」と直接読めるようにする（下記BICYCLE_INFRA_CATEGORIES/
// DESIGNATION_CATEGORIES/ACCIDENT_COLOR_BICYCLE参照）。事故の重大度（死亡事故か否か）は
// ACCIDENT_FATAL_WEIGHTによる実際の重み差があり、これも(B)（下のACCIDENT_SEVERITY_*、
// 竹の時点から既に赤を維持）。
// 「不明・他/対象外/その他（寄与しない側）」はどの種類でも中立グレーのままとし、
// FALLBACK_LINE_OPACITYで薄くする（緑にはしない。「対象外」は「安全と確認済み」ではなく
// 「材料が無い/寄与しない」であり、緑が持つ「良い」という含意とは別物のため）。
const COLOR_NEUTRAL_INDIGO = "#4f46e5";
const COLOR_NEUTRAL_STONE = "#78716c";
const COLOR_NEUTRAL_PINK = "#be185d";

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
// 改善計画（1次/2次の地図上表現の統一）: 車の圧迫感の材料（改善計画T292のcar_stress
// 内部軸、domain/axis_definitions.py: car_stress_bicycle_infra_adjustment
// 「分離自転車道: -2／自転車レーン・共有の車線表示: -1」参照）そのものであり、
// 上から下へ「安全寄り→危険寄り」の実際の順序を持つ。梅で車ストレス
// 5段階に適用したのと同じ手順（AXIS_RAMP_COLORSの4色をそのまま複数段階へ再利用し、
// 段階数の差分だけMaterial系の中間色を新規に挿入）で6段階の緑→赤を割り付ける。
// 1段目(separated)・4〜6段目(shared_pedestrian/roadway/prohibited)はAXIS_RAMP_COLORSの
// 4色をそのまま再利用し、2〜3段目(lane/shared_busway)にMaterial Light Green 500・
// Lime 500を新規に挿入して段差をつなぐ。
const BICYCLE_INFRA_CATEGORIES: CategoryDef[] = [
  { key: "separated", label: "分離自転車道", color: AXIS_RAMP_COLORS[0] },
  { key: "lane", label: "自転車レーン", color: "#8bc34a" },
  { key: "shared_busway", label: "バス専用道等の共用", color: "#cddc39" },
  { key: "shared_pedestrian", label: "歩道[自転車通行可]", color: AXIS_RAMP_COLORS[1] },
  { key: "roadway", label: "車道[専用施設なし]", color: AXIS_RAMP_COLORS[2] },
  { key: "prohibited", label: "自転車通行不可", color: AXIS_RAMP_COLORS[3] },
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
// 改善計画（1次/2次の地図上表現の統一）: 車の圧迫感の材料そのもの（改善計画T292、
// domain/axis_definitions.py: car_stress_designation_adjustment「指定路線に該当: +1」
// 参照）で、N10/N12いずれに該当しても
// 一律+1と扱われ、3カテゴリ間に強弱の差は無い（該当なし=対象外との二値に近い）。
// AXIS_RAMP_COLORSの上位3色（アンバー・オレンジ・赤、いずれも「危険寄り」の範囲）を
// そのまま再利用し、「指定路線に色が付く=車の圧迫感が上がる材料」と直接読めるようにする
// （3値の強弱ではなく、単に見分けが付くよう別々の色を割り当てているだけ）。
const DESIGNATION_CATEGORIES: CategoryDef[] = [
  { key: "emergency_transport", label: "緊急輸送道路[N10]", color: AXIS_RAMP_COLORS[1] },
  { key: "critical_logistics", label: "重要物流道路[N12]", color: AXIS_RAMP_COLORS[2] },
  // 改善計画: 全角括弧（）は表示幅を取り地図表示エリアを圧迫するため半角[]へ統一
  // （設計原則12、docs/complexity-review-2026-08-16.md）。地図上の内訳パネル（幅が狭い）で
  // 見切れやすいという実機報告（モバイル）を機にT104で個別対応した後、システムUI全般の
  // 方針として明文化された。「緊急輸送道路 かつ 重要物流道路」は共有語「道路」の重複表現を
  // 割愛し「緊急輸送 かつ 重要物流道路」へ短縮（ユーザー指定の表記）。折り返し自体もCSS側で
  // 許可済み（MapOverlayControls.module.css: .detailRowLabel）。
  { key: "both", label: "緊急輸送 かつ 重要物流道路[N10＋N12]", color: AXIS_RAMP_COLORS[3] },
];

const designationDefs = buildCategoricalLayerDefs("designation", DESIGNATION_CATEGORIES, "対象外");

// key→labelの対訳表。MapView.tsxのポップアップ表示が参照する（BICYCLE_INFRA_LABELSと同じ理由）。
export const DESIGNATION_LABELS: Record<string, string> = designationDefs.labels;
export const DESIGNATION_LEGEND: LegendEntry[] = designationDefs.legend;
export const DESIGNATION_COLOR_EXPRESSION: unknown[] = designationDefs.colorExpression;
export const DESIGNATION_OPACITY_EXPRESSION: unknown[] = designationDefs.opacityExpression;

// トンネル（一次属性、OSMのtunnelタグ）の色分け定義。designation同様road_surfaceソースの
// 独立レイヤーだが、値は該当区間のみ`true`（未該当はプロパティ欠落）の単純な真偽値のため、
// 文字列列挙用のbuildCategoricalLayerDefsではなく事故（下記ACCIDENT_COLOR_EXPRESSION）と
// 同じcase式で直接書く。
// 改善計画（1次/2次の地図上表現の統一）: tunnelはnight軸（domain/night.py: night_difficulty）の
// 材料の1つで、該当区間は+50点（夜間の危険度が上がる方向）に働く。night軸自体も改善計画
// T278でramp表示（axisMapLayerId("night")、自動導出）を持つようになったが、材料である
// tunnelタグそのものは実体のある一次属性として独立表示する価値があるため、この専用の
// 真偽値レイヤーは維持する。他の2次計算材料（designation等）と同じAXIS_RAMP_COLORSの
// 危険側の色を使う。
const TUNNEL_COLOR = AXIS_RAMP_COLORS[2];

export const TUNNEL_LEGEND: LegendEntry[] = [
  { key: "tunnel", label: "トンネル", color: TUNNEL_COLOR, filter: ["==", ["get", "tunnel"], true] },
  {
    key: "other",
    label: "対象外",
    color: COLOR_UNKNOWN,
    filter: ["!", ["==", ["get", "tunnel"], true]],
    isFallback: true,
  },
];

export const TUNNEL_COLOR_EXPRESSION: unknown[] = [
  "case",
  ["==", ["get", "tunnel"], true],
  TUNNEL_COLOR,
  COLOR_UNKNOWN,
];

export const TUNNEL_OPACITY_EXPRESSION: unknown[] = [
  "case",
  ["==", ["get", "tunnel"], true],
  KNOWN_LINE_OPACITY,
  FALLBACK_LINE_OPACITY,
];

// 一方通行（一次属性、OSM onewayタグ。改善計画T289）の色分け定義。tunnelと同型の
// 単純な真偽値プロパティ（該当区間のみtrue、未該当はプロパティ欠落）。
// tunnel/designationとは異なりAXIS_RAMP_COLORS（危険寄りの色）を使わない——一方通行は
// どの評価軸の材料にもならない（表示専用、mapLayers.tsのpanelHint参照）ため、「色が付く＝
// 評価に効く」という他レイヤーの読み方と混同されないよう、評価軸に使われていない中立色
// （crossing等と同じ青系）を割り当てる。
const ONEWAY_COLOR = "#2563eb";

export const ONEWAY_LEGEND: LegendEntry[] = [
  { key: "oneway", label: "一方通行", color: ONEWAY_COLOR, filter: ["==", ["get", "oneway"], true] },
  {
    key: "other",
    label: "対象外",
    color: COLOR_UNKNOWN,
    filter: ["!", ["==", ["get", "oneway"], true]],
    isFallback: true,
  },
];

export const ONEWAY_COLOR_EXPRESSION: unknown[] = [
  "case",
  ["==", ["get", "oneway"], true],
  ONEWAY_COLOR,
  COLOR_UNKNOWN,
];

export const ONEWAY_OPACITY_EXPRESSION: unknown[] = [
  "case",
  ["==", ["get", "oneway"], true],
  KNOWN_LINE_OPACITY,
  FALLBACK_LINE_OPACITY,
];

// 外部静的データソース T50（警察庁交通事故統計）の色分け定義。
// backend/app/domain/accident.py: involves_bicycle/is_fatalと同じ意味論
// （involves_bicycle=自転車が当事者A/Bのいずれかに該当、fatal=死者数>0）。
//
// 改善計画（1次の点要素の順序付け）: 竹では「当事者（自転車関連/その他）は事実の種類の
// 区別であり重大度ではない」という理由で評価色の赤から中立色へ差し替えていたが、実際には
// 順序があることが判明した。事故密度（2次、accident_density）はbackend/app/infrastructure/
// road_graph_repository.py:
// bicycle_only=true固定（involves_bicycleのみ）で集計しており、自転車関連の事故だけが
// 事故密度スコアへ寄与し、その他（自転車が絡まない事故）は寄与しない
// （domain/accident.py: distance_weighted_accident_density）。つまり指定路線の
// 該当/対象外と同じ「材料として寄与するか否か」の二値で、自転車関連＝寄与する側は
// AXIS_RAMP_COLORSの赤（2次の危険側と同じ意味）、その他＝寄与しない側は中立グレーのまま
// にする。重大度（死亡事故か否か）は下のACCIDENT_SEVERITY_*を参照（そちらは
// ACCIDENT_FATAL_WEIGHTによる実際の重み差があるため、竹の時点から既に赤を維持している）。
const ACCIDENT_COLOR_BICYCLE = AXIS_RAMP_COLORS[3];
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
// と対にして凡例側にも残す（bicycleInfra等と同じ「不明・他」の扱い）。
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
  | "bicycleInfra"
  | "designation"
  | "tunnel"
  | "oneway"
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
  { axisId: "bicycleInfra", layerId: "bicycleInfra", legend: BICYCLE_INFRA_LEGEND },
  { axisId: "designation", layerId: "designation", legend: DESIGNATION_LEGEND },
  { axisId: "tunnel", layerId: "tunnel", legend: TUNNEL_LEGEND },
  { axisId: "oneway", layerId: "oneway", legend: ONEWAY_LEGEND },
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

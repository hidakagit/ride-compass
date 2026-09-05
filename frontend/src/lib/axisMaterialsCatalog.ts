// 軸スタジオ（改善計画T270）の材料選択候補の静的フォールバック。改善計画T277で
// backend/app/domain/material_catalog.py: MATERIAL_CATALOGが正式な単一ソースになり、
// 軸コンポーザーは通常`hooks/useMaterialCatalog.ts`経由でGET /api/material-catalogから
// 動的取得する。本定数は取得失敗時（オフライン・API未起動等）のフォールバックとしてのみ
// 残す——新しい材料を増やす際にこのファイルの更新は必須ではない（動的取得が失敗した
// 場合のみ古いまま表示される）。
//
// これはbackend側`compute_edge_axis_scores`/`compute_edge_costs_bulk`が組み立てる
// 材料辞書のキーそのものであり（目論見書7章・歯止め4「材料の天井」）、
// backend/app/domain/registry_defaults.pyの一次属性（OSM生タグ等）とは別の語彙のため、
// あちらのカタログをそのまま流用できない（両者は将来統合の余地がある課題として
// docs/decisions/t221-axis-registry.md「T12との関係」に記録済み）。
export type AxisMaterialDType = "numeric" | "boolean" | "categorical";

/** 軸スタジオの折れ点編集を助ける「値の目安」1点。backend/app/domain/
 * material_catalog.py: MaterialReferencePointが単一ソース。 */
export interface AxisMaterialReferencePoint {
  label: string;
  value: number;
}

export interface AxisMaterialOption {
  id: string;
  /** 改善計画T345さらなるフォローアップ2: 「論理名 - 物理名」形式（例: "道路種別 - highway"）。
   * backend/app/domain/material_catalog.py: MaterialSpec.full_label()と同じ形式で、
   * 動的取得（GET /api/material-catalog）が失敗した場合のフォールバックとして揃える。 */
  label: string;
  /** 改善計画T345: 情報アイコン(ⓘ)から表示する説明文。backend/app/domain/
   * material_catalog.py: MaterialSpec.descriptionが単一ソース。 */
  description: string;
  /** "numeric"=数値材料（BreakpointLinearShape向け）、"boolean"=真偽値材料
   * （BreakpointLinearShape/CategoricalShape向け）、"categorical"=文字列多値材料
   * （CategoricalShapeがbool/str両方に対応、改善計画T292）。 */
  dtype: AxisMaterialDType;
  /** 「値の目安」一覧。値を持たない材料や静的フォールバック（本ファイル）では
   * 省略されうる。 */
  referencePoints?: readonly AxisMaterialReferencePoint[];
}

// backend/app/domain/material_catalog.py: MATERIAL_CATALOGのうちdisplay_only=Falseの
// 材料（GET /api/material-catalogの公開レスポンスと同じ集合、改善計画T338）と同じ内容。
// 動的取得が失敗した場合のみこの一覧が使われるため、backend側の変更に追従できていなくても
// 軸スタジオの選択肢が古くなるだけで実害はないが、削除済みの材料id（car_stress_level）や
// display_only化された材料id（designation、改善計画T338）を含んだままだと選択→保存時に
// AxisDefinitionPayload._check_materials_are_knownの"unknown material(s)"エラーには
// ならないものの選択肢として不適切なままになるため、削除・除外済みidだけは残さない。
export const AXIS_MATERIAL_OPTIONS: readonly AxisMaterialOption[] = [
  {
    id: "gradient_percent",
    label: "勾配%（符号付き） - gradient_percent",
    description: "国土地理院の標高データから算出した進行方向の勾配（%）。登り坂はプラス、下り坂はマイナスです。",
    dtype: "numeric",
  },
  {
    id: "wind_penalty",
    label: "向かい風ペナルティ(m/s、正=向かい風) - wind_penalty",
    description:
      "出発時刻の気象予報とルートの進行方向から算出した向かい風の強さ（m/s）。追い風・無風はマイナス〜0、向かい風が強いほど大きなプラスの値になります。",
    dtype: "numeric",
  },
  {
    id: "surface_good",
    label: "舗装良否 - surface_good",
    description: "OSMの路面タグ(surface)から判定した舗装の良否。true=舗装良好、false=未舗装等。",
    dtype: "boolean",
  },
  {
    id: "stop_count_per_km",
    label: "停止密度(回/km) - stop_count_per_km",
    description: "信号・一時停止・踏切など、進行を妨げる要因の1kmあたりの発生回数。",
    dtype: "numeric",
  },
  {
    id: "intersection_count_per_km",
    label: "交差点密度(回/km) - intersection_count_per_km",
    description: "接続する道路が3本以上ある交差点の1kmあたりの発生回数。",
    dtype: "numeric",
  },
  {
    id: "accident_count_per_km_year",
    label: "事故密度(件/(km・年)) - accident_count_per_km_year",
    description: "警察庁の事故データに基づく、1kmあたり・1年あたりの人身事故件数。",
    dtype: "numeric",
  },
  {
    id: "lit",
    label: "街灯あり - lit",
    description: "OSMの街灯タグ(lit=yes)に該当する区間はtrue。タグ不在はfalse（街灯なし扱い）。",
    dtype: "boolean",
  },
  {
    id: "has_tunnel",
    label: "トンネル - has_tunnel",
    description: "OSMのトンネルタグ(tunnel=yes)に該当する区間はtrue。",
    dtype: "boolean",
  },
  {
    id: "bridge",
    label: "橋・高架 - bridge",
    description: "OSMの橋・高架タグ(bridge=yes)に該当する区間はtrue。",
    dtype: "boolean",
  },
  {
    id: "motor_vehicle_no",
    label: "自動車通行不可 - motor_vehicle_no",
    description: "OSMのタグ(motor_vehicle=no)から判定した、自動車が通行できない区間かどうか。",
    dtype: "boolean",
  },
  {
    id: "oneway",
    label: "一方通行 - oneway",
    description:
      "OSMのタグから判定した一方通行区間かどうか。現時点では評価軸の材料として配線されておらず、選んでもこの軸は常に「データなし」として扱われます（地図表示専用）。",
    dtype: "boolean",
  },
  {
    id: "maxspeed_kmh",
    label: "制限速度(km/h) - maxspeed_kmh",
    description: "OSMの制限速度タグ(maxspeed)から解析した制限速度（km/h）。",
    dtype: "numeric",
  },
  {
    id: "lanes_count",
    label: "車線数 - lanes_count",
    description: "OSMの車線数タグ(lanes)から解析した車線数。",
    dtype: "numeric",
  },
  {
    id: "highway",
    label: "道路種別 - highway",
    description: "OSMの道路種別タグ(highway)の生値（例: residential/primary/cycleway等）。値ごとに個別のスコアを設定できます。",
    dtype: "categorical",
  },
  {
    id: "surface",
    label: "路面種別 - surface",
    description: "OSMの路面種別タグ(surface)の生値（例: asphalt/gravel等）。良否(舗装良否)だけでなく種別ごとに細かくスコアを設定したい場合に使います。",
    dtype: "categorical",
  },
  {
    id: "highway_is_cycleway",
    label: "道路種別が自転車道 - highway_is_cycleway",
    description: "道路種別(highway)自体が自転車道(cycleway)かどうか。",
    dtype: "boolean",
  },
  {
    id: "cycleway_has_track",
    label: "自転車道(track)を併設 - cycleway_has_track",
    description: "車道と分離された自転車道(cycleway=track)を併設しているかどうか。",
    dtype: "boolean",
  },
  {
    id: "cycleway_has_lane",
    label: "自転車レーン(lane)を併設 - cycleway_has_lane",
    description: "車道上に線で区切られた自転車レーン(cycleway=lane)を併設しているかどうか。",
    dtype: "boolean",
  },
  {
    id: "cycleway_has_shared",
    label: "バス共用等の自転車レーンを併設 - cycleway_has_shared",
    description: "バス専用レーン共用など、簡易な自転車レーン(cycleway=shared_busway/shared_lane)を併設しているかどうか。",
    dtype: "boolean",
  },
  {
    id: "is_designated",
    label: "指定路線該当（真偽） - is_designated",
    description: "緊急輸送道路・重要物流道路のいずれかに指定されているかどうか（種別は区別しません）。",
    dtype: "boolean",
  },
  {
    id: "is_emergency_transport",
    label: "緊急輸送道路該当[N10]（真偽） - is_emergency_transport",
    description:
      "緊急輸送道路[N10]に指定されているかどうか。現時点では評価軸の材料として配線されておらず、選んでもこの軸は常に「データなし」として扱われます（地図表示専用。評価で使う場合は指定路線該当を使ってください）。",
    dtype: "boolean",
  },
  {
    id: "is_critical_logistics",
    label: "重要物流道路該当[N12]（真偽） - is_critical_logistics",
    description:
      "重要物流道路[N12]に指定されているかどうか。現時点では評価軸の材料として配線されておらず、選んでもこの軸は常に「データなし」として扱われます（地図表示専用。評価で使う場合は指定路線該当を使ってください）。",
    dtype: "boolean",
  },
  {
    id: "smoothness",
    label: "路面の状態 - smoothness",
    description: "OSMの路面状態タグ(smoothness)の生値（excellent〜impassableの7段階）。同じ路面種別(surface)でも実際の荒れ具合を区別したい場合に使います。",
    dtype: "categorical",
  },
  {
    id: "tracktype",
    label: "未舗装路グレード(tracktype) - tracktype",
    description: "OSMの未舗装路グレードタグ(tracktype)の生値（grade1[良好]〜grade5[粗悪]）。",
    dtype: "categorical",
  },
];

export function materialLabel(materialId: string): string {
  return AXIS_MATERIAL_OPTIONS.find((m) => m.id === materialId)?.label ?? materialId;
}

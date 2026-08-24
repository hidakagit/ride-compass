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

export interface AxisMaterialOption {
  id: string;
  label: string;
  /** "numeric"=数値材料（BreakpointLinearShape向け）、"boolean"=真偽値材料
   * （CategoricalShape/FlagSumShape向け）、"categorical"=文字列多値材料
   * （CategoricalShapeがbool/str両方に対応、改善計画T292）。 */
  dtype: AxisMaterialDType;
}

// backend/app/domain/material_catalog.py: MATERIAL_CATALOGと同じ内容（改善計画T292で
// car_stress_levelを撤去・highway等の新規材料を追加した後の状態）。動的取得が失敗した
// 場合のみこの一覧が使われるため、backend側の変更に追従できていなくても軸スタジオの
// 選択肢が古くなるだけで実害はないが、削除済みの材料id（car_stress_level）を含んだまま
// だと選択→保存時にAxisDefinitionPayload._check_materials_are_knownの
// "unknown material(s)"エラーになるため、削除済みidだけは残さない。
export const AXIS_MATERIAL_OPTIONS: readonly AxisMaterialOption[] = [
  { id: "gradient_percent", label: "勾配%（符号付き）", dtype: "numeric" },
  { id: "wind_penalty", label: "向かい風ペナルティ(m/s、正=向かい風)", dtype: "numeric" },
  { id: "surface_good", label: "舗装良否", dtype: "boolean" },
  { id: "stop_count_per_km", label: "停止密度(回/km)", dtype: "numeric" },
  { id: "intersection_count_per_km", label: "交差点密度(回/km)", dtype: "numeric" },
  { id: "accident_count_per_km_year", label: "事故密度(件/(km・年))", dtype: "numeric" },
  { id: "no_lit", label: "街灯なし", dtype: "boolean" },
  { id: "has_tunnel", label: "トンネル", dtype: "boolean" },
  { id: "bridge", label: "橋・高架", dtype: "boolean" },
  { id: "motor_vehicle_no", label: "自動車通行不可", dtype: "boolean" },
  { id: "oneway", label: "一方通行", dtype: "boolean" },
  { id: "maxspeed_kmh", label: "制限速度(km/h)", dtype: "numeric" },
  { id: "lanes_count", label: "車線数", dtype: "numeric" },
  { id: "highway", label: "道路種別", dtype: "categorical" },
  { id: "surface", label: "路面種別", dtype: "categorical" },
  { id: "bicycle_infra", label: "自転車インフラ種別", dtype: "categorical" },
  { id: "cycleway_class", label: "自転車レーン種別", dtype: "categorical" },
  { id: "designation", label: "指定路線", dtype: "categorical" },
  { id: "is_designated", label: "指定路線該当（真偽）", dtype: "boolean" },
  { id: "smoothness", label: "路面の状態", dtype: "categorical" },
];

export function materialLabel(materialId: string): string {
  return AXIS_MATERIAL_OPTIONS.find((m) => m.id === materialId)?.label ?? materialId;
}

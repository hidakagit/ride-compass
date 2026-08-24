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
export interface AxisMaterialOption {
  id: string;
  label: string;
  /** true=真偽値材料（CategoricalShape/FlagSumShape向け）、false=数値材料（BreakpointLinearShape向け）。 */
  boolean: boolean;
}

export const AXIS_MATERIAL_OPTIONS: readonly AxisMaterialOption[] = [
  { id: "gradient_percent", label: "勾配%（符号付き）", boolean: false },
  { id: "wind_penalty", label: "向かい風ペナルティ(m/s、正=向かい風)", boolean: false },
  { id: "surface_good", label: "舗装良否", boolean: true },
  { id: "stop_count_per_km", label: "停止密度(回/km)", boolean: false },
  { id: "intersection_count_per_km", label: "交差点密度(回/km)", boolean: false },
  { id: "accident_count_per_km_year", label: "事故密度(件/(km・年))", boolean: false },
  { id: "car_stress_level", label: "車ストレスレベル(1-5、レシピ判定済み)", boolean: false },
  { id: "no_lit", label: "街灯なし", boolean: true },
  { id: "has_tunnel", label: "トンネル", boolean: true },
];

export function materialLabel(materialId: string): string {
  return AXIS_MATERIAL_OPTIONS.find((m) => m.id === materialId)?.label ?? materialId;
}

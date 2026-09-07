import generatedMaterials from "@/types/generated/material-catalog.json";

// 軸スタジオの材料選択候補の静的フォールバック。
// backend/app/domain/material_catalog.py: MATERIAL_CATALOGが単一ソースで、軸コンポーザーは
// 通常`hooks/useMaterialCatalog.ts`経由でGET /api/material-catalogから動的取得する。
// 本定数は取得失敗時（オフライン・API未起動等）のフォールバック。
//
// **一覧は手書きせず生成物（material-catalog.json、export_openapi.pyが書き出す）から
// 導出する**——手書きで持っていたころは、APIが落ちているときだけ選択肢が古いという
// 気づく機会の無いドリフトが実際に発生していた（公開材料に対し1件欠落）。
//
// これはbackend側`compute_edge_axis_scores`/`compute_edge_costs_bulk`が組み立てる
// 材料辞書のキーそのものであり、backend/app/domain/registry_defaults.pyの一次属性
// （OSM生タグ等）とは別の語彙のため、あちらのカタログをそのまま流用できない（両者は
// 将来統合の余地がある課題として docs/decisions/t221-axis-registry.md「T12との関係」に
// 記録済み）。
export type AxisMaterialDType = "numeric" | "boolean" | "categorical";

/** 軸スタジオの折れ点編集を助ける「値の目安」1点。backend/app/domain/
 * material_catalog.py: MaterialReferencePointが単一ソース。 */
export interface AxisMaterialReferencePoint {
  label: string;
  value: number;
}

export interface AxisMaterialOption {
  id: string;
  /** 「論理名 - 物理名」形式（例: "道路種別 - highway"）。backend/app/domain/
   * material_catalog.py: MaterialSpec.full_label()と同じ形式で、動的取得
   * （GET /api/material-catalog）が失敗した場合のフォールバックとして揃える。 */
  label: string;
  /** 情報アイコン(ⓘ)から表示する説明文。backend/app/domain/
   * material_catalog.py: MaterialSpec.descriptionが単一ソース。 */
  description: string;
  /** "numeric"=数値材料（BreakpointLinearShape向け）、"boolean"=真偽値材料
   * （BreakpointLinearShape/CategoricalShape向け）、"categorical"=文字列多値材料
   * （CategoricalShapeがbool/str両方に対応）。 */
  dtype: AxisMaterialDType;
  /** 値の単位（凡例・数値表示用、無次元・真偽値・カテゴリ値は空文字）。
   * backend/app/domain/material_catalog.py: MaterialSpec.unitが単一ソース。 */
  unit: string;
  /** 「値の目安」一覧。値を持たない材料や静的フォールバック（本ファイル）では
   * 省略されうる。 */
  referencePoints?: readonly AxisMaterialReferencePoint[];
}

// 生成物からフォールバック一覧を組み立てる。生成物はbackendの`axis_studio_materials()`
// （`display_only=False`の公開材料）と1対1で、`GET /api/material-catalog`の応答と同じ集合。
// 「値の目安」（referencePoints）は動的取得でのみ得られるためフォールバックには含めない。
export const AXIS_MATERIAL_OPTIONS: readonly AxisMaterialOption[] = generatedMaterials.map((m) => ({
  id: m.material_id,
  // backendの`MaterialSpec.full_label()`と同じ「論理名 - 物理名」形式。
  label: `${m.label} - ${m.material_id}`,
  description: m.description,
  dtype: m.dtype as AxisMaterialDType,
  unit: m.unit,
}));

/** 材料idの表示名（静的フォールバック側）。動的取得済みの一覧があるときは
 * materialCatalogLabelを使う。 */
export function materialLabel(materialId: string): string {
  return AXIS_MATERIAL_OPTIONS.find((m) => m.id === materialId)?.label ?? materialId;
}

/** 材料idの表示名（動的取得した一覧から引く）。未知idはidをそのまま返す。 */
export function materialCatalogLabel(materialId: string, materials: readonly AxisMaterialOption[]): string {
  return materials.find((m) => m.id === materialId)?.label ?? materialId;
}

/** material_valuesの生値1件を「値 単位」表記にする。単位が無い（無次元）材料は値のみ。 */
export function formatMaterialValue(materialId: string, value: number, materials: readonly AxisMaterialOption[]): string {
  const unit = materials.find((m) => m.id === materialId)?.unit ?? "";
  return unit ? `${value.toFixed(2)} ${unit}` : value.toFixed(2);
}

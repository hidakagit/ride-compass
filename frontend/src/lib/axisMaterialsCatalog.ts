// 軸スタジオ・ルート結果が扱う材料の型と、材料idを表示へ変える関数。
// 一覧そのものは`hooks/useMaterialCatalog.ts`が`GET /api/material-catalog`から取る。

export type AxisMaterialDType = "numeric" | "boolean" | "categorical";

/** 軸スタジオの折れ点編集を助ける「値の目安」1点。 */
export interface AxisMaterialReferencePoint {
  label: string;
  value: number;
}

export interface AxisMaterialOption {
  id: string;
  /** 「論理名 - 物理名」形式（例: "道路種別 - highway"）。 */
  label: string;
  /** 論理名だけ（例: "道路種別"）。物理名を出す意味が無い一般向けの表示が使う。
   * `label`から物理名を削って作り直さない——論理名に区切り文字が含まれたときに壊れる。 */
  name: string;
  /** 情報アイコン(ⓘ)から表示する説明文。 */
  description: string;
  /** "numeric"=数値材料（折れ点向け）、"boolean"=真偽値材料、"categorical"=文字列多値材料。 */
  dtype: AxisMaterialDType;
  /** 値の単位（凡例・数値表示用、無次元・真偽値・カテゴリ値は空文字）。 */
  unit: string;
  referencePoints?: readonly AxisMaterialReferencePoint[];
}

/** 選択肢へ出す材料の表記。**単位は`unit`が唯一の正**で、ラベルには入れない——ラベルへ
 *  埋めると、単位を別に添える画面で「制限速度(km/h) 35km/h」のように二重になる。 */
export function materialOptionText(option: { label: string; unit?: string }): string {
  return option.unit ? `${option.label}（${option.unit}）` : option.label;
}

/** 材料idの表示名。未知idはidをそのまま返す。 */
export function materialCatalogLabel(materialId: string, materials: readonly AxisMaterialOption[]): string {
  return materials.find((m) => m.id === materialId)?.label ?? materialId;
}

/** 一般向けの表示に使う材料名（論理名だけ）。物理名まで出す軸スタジオは
 * `materialCatalogLabel`を使う。 */
export function materialCatalogName(materialId: string, materials: readonly AxisMaterialOption[]): string {
  return materials.find((m) => m.id === materialId)?.name ?? materialId;
}

/** material_valuesの生値1件を「値 単位」表記にする。単位が無い（無次元）材料は値のみ。 */
export function formatMaterialValue(
  materialId: string,
  value: number,
  materials: readonly AxisMaterialOption[],
): string {
  const unit = materials.find((m) => m.id === materialId)?.unit ?? "";
  return unit ? `${value.toFixed(2)} ${unit}` : value.toFixed(2);
}

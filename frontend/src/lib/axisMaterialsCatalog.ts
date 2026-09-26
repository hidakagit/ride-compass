// 軸スタジオ・ルート結果が扱う材料の一覧と、材料idを表示へ変える関数。
// 一覧はbackendの材料の宣言をビルド時に書き出した生成物から作る（材料はコードで決まり、
// 再デプロイでしか変わらない）。実行時に取りに行かないので、読み込み中も取得失敗も無い。

import type { components } from "@/types/generated/api";
import materialCatalog from "@/types/generated/material-catalog.json";

/** 材料の値の種類。**正本はbackend**（`domain/material_catalog.py: MaterialDType`）で、
 * ここは契約から引くだけ——写すと、種類が1つ増えたとき片側だけ知っている状態になる。 */
type AxisMaterialDType = components["schemas"]["MaterialCoverageEntry"]["dtype"];

/** 軸スタジオの折れ点編集を助ける「値の目安」1点。 */
interface AxisMaterialReferencePoint {
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

/** 材料の一覧（backendの`MATERIAL_CATALOG`の登録順）。 */
export const MATERIAL_CATALOG: readonly AxisMaterialOption[] = materialCatalog.map((material) => ({
  id: material.material_id,
  label: material.label,
  name: material.name,
  description: material.description,
  // JSONの生成物は型が`string`へ広がる。値は契約の`MaterialDType`と同じ宣言から書き出される。
  dtype: material.dtype as AxisMaterialDType,
  unit: material.unit,
  referencePoints: material.reference_points,
}));

/** 選択肢へ出す材料の表記。**単位は`unit`が唯一の正**で、ラベルには入れない——ラベルへ
 *  埋めると、単位を別に添える画面で「制限速度(km/h) 35km/h」のように二重になる。 */
export function materialOptionText(option: { label: string; unit?: string }): string {
  return option.unit ? `${option.label}（${option.unit}）` : option.label;
}

/** 軸スタジオ（管理画面）に出す材料名（「論理名 - 物理名」）。物理名を見せるのが目的の
 * 画面なので、カタログに無いidはidのまま返す。一般向けの画面では使わない。 */
export function materialCatalogLabel(materialId: string, materials: readonly AxisMaterialOption[]): string {
  return materials.find((m) => m.id === materialId)?.label ?? materialId;
}

/** 一般向けの表示に使う材料名（論理名だけ）。**カタログに無いidはundefined**——idで埋めると
 * 内部名がそのまま画面に出るため、呼び出し側はその材料を出さない。 */
export function materialCatalogName(materialId: string, materials: readonly AxisMaterialOption[]): string | undefined {
  return materials.find((m) => m.id === materialId)?.name;
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

// 地図のチップに出す軸の一覧。軸カタログの項目をそのまま移す（名前・略名・アイコン・説明の正本は軸自身）。

import { axisMapLayerId, type AxisMapLayerId } from "@/lib/mapDisplay/axisLayers";
import type { AxisCatalogEntry } from "@/types/route";

export interface SecondaryAxisSummary {
  axisId: string;
  label: string;
  description: string;
  chipLabel: string;
  /** 地図の専用レイヤー。無い軸はチップを薄く出す。 */
  layerId?: AxisMapLayerId;
  /** 軸が読む材料の一次属性id。 */
  primaryAttributeIds: readonly string[];
  iconId?: string;
  /** 表示の設定パネルでこの軸の行の(i)が出す説明。無ければ(i)を出さない。 */
  panelHint?: string;
  /** 地図の表示の種類からは導けない（表示が`none`でも専用配信を持つ軸がある）。 */
  dedicatedWayValueLayer?: boolean;
  rawValueUnit?: string | null;
  rawValueTotalUnit?: string | null;
  materialBreakdown?: readonly AxisMaterialBreakdown[];
}

/** カタログの`material_breakdown`をフロントの命名へ移す（軸の一覧を組む2か所が共有し、項目の移し忘れを防ぐ）。 */
export function materialBreakdownFromCatalog(entries: AxisCatalogEntry["material_breakdown"]): AxisMaterialBreakdown[] {
  return entries.map((entry) => ({
    materialId: entry.material_id,
    label: entry.label,
    dtype: entry.dtype,
    unit: entry.unit,
    share: entry.share,
    valueLabels: entry.value_labels,
  }));
}

/** 生値の単位が定まらない軸の内訳1件（材料と、軸の生値に占める割合。正規化重みの降順）。 */
export interface AxisMaterialBreakdown {
  materialId: string;
  label: string;
  /** `numeric`＝距離加重平均＋単位、`boolean`＝該当区間の延長割合。 */
  dtype: string;
  /** numeric材料の単位。真偽値材料は空文字。 */
  unit: string;
  share: number;
  /** categorical材料の「タグ生値→論理名」対訳（他の型では空）。フロントは対応表を持たない。 */
  valueLabels?: Readonly<Record<string, string>>;
}

function layerIdFor(axis: AxisCatalogEntry): AxisMapLayerId | undefined {
  if (axis.display.kind === "ramp") return axisMapLayerId(axis.axis_id);
  return undefined;
}

/** カタログの並び順のまま。一覧から外すのは軸の`show_map_icon`だけで決める（軸idの名指しで外さない）。 */
export function secondaryAxesFromCatalogAxes(axes: readonly AxisCatalogEntry[]): SecondaryAxisSummary[] {
  return axes
    .filter((axis) => axis.show_map_icon)
    .map((axis) => ({
      axisId: axis.axis_id,
      label: axis.display.label,
      description: axis.description,
      chipLabel: axis.chip_label ?? axis.display.label,
      layerId: layerIdFor(axis),
      primaryAttributeIds: axis.primary_attribute_ids,
      iconId: axis.icon_id ?? undefined,
      panelHint: axis.panel_hint ?? undefined,
      dedicatedWayValueLayer: axis.dedicated_way_value_layer,
      rawValueUnit: axis.raw_value_unit,
      rawValueTotalUnit: axis.raw_value_total_unit,
      materialBreakdown: materialBreakdownFromCatalog(axis.material_breakdown),
    }));
}

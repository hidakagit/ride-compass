// 地図のチップに出す軸の一覧。軸の共通の項目は`catalogAxis.ts`が行から移し、ここは地図のチップの項目だけを足す。

import { catalogAxisFromEntry, type CatalogAxis } from "@/lib/catalogAxis";
import { axisMapLayerId, type AxisMapLayerId } from "@/lib/mapDisplay/axisLayers";
import type { AxisCatalogEntry } from "@/types/route";

export interface SecondaryAxisSummary extends CatalogAxis {
  /** 地図の専用レイヤー。無い軸はチップを薄く出す。 */
  layerId?: AxisMapLayerId;
  /** 軸が読む材料の一次属性id。 */
  primaryAttributeIds: readonly string[];
}

/** カタログの並び順のまま。一覧から外すのは軸の`show_map_icon`だけで決める（軸idの名指しで外さない）。 */
export function secondaryAxesFromCatalogAxes(axes: readonly AxisCatalogEntry[]): SecondaryAxisSummary[] {
  return axes
    .filter((axis) => axis.show_map_icon)
    .map((axis) => ({
      ...catalogAxisFromEntry(axis),
      layerId: axis.display.kind === "ramp" ? axisMapLayerId(axis.axis_id) : undefined,
      primaryAttributeIds: axis.primary_attribute_ids,
    }));
}

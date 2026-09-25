// 一次属性（生データ）の名前と、地図のレイヤーとの対応。どちらも源泉の宣言から導く。

import { mapDisplay } from "@/types/generated/mapDisplay";
import type { MapLayerId } from "./mapLayers";
import { primaryAttributes as primaryAttributeCatalog } from "@/types/generated/primaryAttributes";

/** 属性id→正式名。 */
export const PRIMARY_ATTRIBUTE_LABELS: Record<string, string> = Object.fromEntries(
  primaryAttributeCatalog.map((attr) => [attr.attr_id, attr.label]),
);

/** 一次属性のうち地図に出るもの（源泉が決める）。レイヤーの名前は属性idそのもので、対応表を持たない。 */
const MAP_LAYER_ATTR_IDS: ReadonlySet<string> = new Set(mapDisplay.layers.map((layer) => layer.id));

/** 属性idのうち地図のレイヤーを持つもの（重複なし）。 */
export function primaryAttributeIdsToLayerIds(attrIds: readonly string[]): readonly MapLayerId[] {
  const layerIds = attrIds.filter((attrId): attrId is MapLayerId => MAP_LAYER_ATTR_IDS.has(attrId));
  return Array.from(new Set(layerIds));
}

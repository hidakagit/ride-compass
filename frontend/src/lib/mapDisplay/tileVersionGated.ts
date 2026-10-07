// タイルの世代（軸カタログの応答が運ぶ）が届くまで描けない地図の情報。地図のレイヤーと、取れないことを告げる文が
// 同じ集合を読む。

import { mapDisplay } from "@/types/generated/mapDisplay";
import regionTileConfig from "@/types/generated/region-tile-config.json";

/** 世代が届くまで要求できない情報源（世代を配るタイルの系統の名前が、そのまま情報源の名前）。 */
export const TILE_VERSION_GATED_SOURCES: ReadonlySet<string> = new Set(regionTileConfig.tile_version_kinds);

/** 世代が届くまで描けないレイヤーを持つ、地図のチップのグループの名前（グループの順）。 */
export function tileVersionGatedGroupLabels(): string[] {
  const gatedGroups = new Set(
    mapDisplay.layers
      .filter((layer) => TILE_VERSION_GATED_SOURCES.has(layer.dataSource))
      .map((layer) => mapDisplay.layerCategories.find((category) => category.key === layer.category)?.group),
  );
  return mapDisplay.overlayGroups.filter((group) => gatedGroups.has(group.key)).map((group) => group.label);
}

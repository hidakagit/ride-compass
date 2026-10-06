// 地図が読む軸カタログを、テストが架空の軸から組む。本番と同じ応答からの導出（`mapAxisCatalogFromResponse`）を通す。
import { mapAxisCatalogFromResponse, type MapAxisCatalog } from "@/features/map/mapAxisCatalog";
import { catalogResponse } from "@/testing/catalogAxes";
import type { AxisCatalogEntry, AxisCatalogResponse } from "@/types/route";

export function mapCatalogOf(
  entries: readonly AxisCatalogEntry[],
  overrides: Partial<Omit<AxisCatalogResponse, "axes">> = {},
): MapAxisCatalog {
  return mapAxisCatalogFromResponse(catalogResponse(entries, overrides));
}

// 地図が読む軸カタログ（共有の軸の一覧と、地図だけが読むもの）を、テストが架空の軸から組む。どちらも本番と同じ
// 応答からの導出（`axisCatalogFromResponse`・`mapAxisCatalogFromResponse`）を通す。
import { mapAxisCatalogFromResponse, type MapAxisCatalog } from "@/features/map/mapAxisCatalog";
import { axisCatalogFromResponse, type AxisCatalog } from "@/lib/axisCatalog";
import { catalogResponse } from "@/testing/catalogAxes";
import type { AxisCatalogEntry, AxisCatalogResponse } from "@/types/route";

export function mapCatalogOf(
  entries: readonly AxisCatalogEntry[],
  overrides: Partial<Omit<AxisCatalogResponse, "axes">> = {},
): MapAxisCatalog & Pick<AxisCatalog, "axes"> {
  const response = catalogResponse(entries, overrides);
  return { ...mapAxisCatalogFromResponse(response), axes: axisCatalogFromResponse(response).axes };
}

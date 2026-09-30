"use client";

import { useAxisCatalogSelect } from "@/hooks/useAxisCatalog";
import { EMPTY_MAP_AXIS_CATALOG, mapAxisCatalogFromResponse, type MapAxisCatalog } from "@/features/map/mapAxisCatalog";

/** 軸カタログのうち地図だけが読むもの（地図の表示の軸・タイルの世代）。取得は共有の軸カタログと1つで、届くまで・
 * 失敗の間は軸もタイルの世代も無い。届いたかどうかは共有の軸カタログの`loaded`・`failed`で見る。 */
export function useMapAxisCatalog(): MapAxisCatalog {
  return useAxisCatalogSelect(mapAxisCatalogFromResponse).data ?? EMPTY_MAP_AXIS_CATALOG;
}

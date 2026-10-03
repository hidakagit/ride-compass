"use client";

import { useQuery } from "@tanstack/react-query";
import { getAxisCatalog } from "@/services/axisCatalogApi";
import { setTileVersions } from "@/services/regionApi";
import { axisCatalogFromResponse, EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";
import { getQueryClient } from "@/lib/queryClient";
import type { FetchFailure } from "@/types/fetchFailure";

const AXIS_CATALOG_QUERY_KEY = ["axis-catalog"] as const;

const FAILED_CATALOG: AxisCatalog = { ...EMPTY_CATALOG, failed: true };

async function fetchAxisCatalog(): Promise<AxisCatalog> {
  const response = await getAxisCatalog();
  // タイルの世代は地図のソースのURLに入るため、カタログより先に渡す。
  setTileVersions(response.tile_versions);
  return axisCatalogFromResponse(
    response.axes,
    response.tile_runtime_scales,
    response.client_tuning,
    response.accident_years,
  );
}

/** 軸カタログの取得をやり直す（`failed`状態からの明示的な再試行導線用）。
 * 既に成功していれば何もしない。再取得中は`failed`を下ろし、UIが「取得中」へ戻る。 */
export function retryAxisCatalogFetch(): void {
  const client = getQueryClient();
  if (client.getQueryData(AXIS_CATALOG_QUERY_KEY) !== undefined) return;
  void client.refetchQueries({ queryKey: AXIS_CATALOG_QUERY_KEY });
}

const AXIS_CATALOG_FETCH_FAILURE: FetchFailure = {
  id: "axis-catalog",
  label: "軸一覧",
  effect:
    "地図の道路・スポット・事故を表示できません。ルートは重み配分を変えていても反映できず、既定の配分で作ります。ルートの合成も使えません。",
  onRetry: retryAxisCatalogFetch,
};

/** 軸カタログが取れていないことの常設ヘッダーの印の項目（取れていれば・取得中なら無い）。 */
export function axisCatalogFetchFailure(catalog: AxisCatalog): FetchFailure | null {
  return catalog.failed ? AXIS_CATALOG_FETCH_FAILURE : null;
}

/** 軸カタログ。マウントのたびに取り、軸スタジオで公開した軸を再デプロイなしに反映する。届くまで・失敗したときは
 * 軸0件のカタログを返す（`loaded`・`failed`で見分ける）。一度届いたカタログは、後の取得の失敗で巻き戻さない。
 * **重みを送るような「今の公開軸と一致していなければならない」処理は`loaded`を確かめる**——届く前の空の一覧で
 * 送ると、公開軸と食い違う重みになる。 */
export function useAxisCatalog(): AxisCatalog {
  const { data, isError, isFetching } = useQuery(
    // 読み手が一時いなくなっても捨てない（捨てると、次にマウントした部品が軸0件から始まる）。
    { queryKey: AXIS_CATALOG_QUERY_KEY, queryFn: fetchAxisCatalog, gcTime: Infinity },
    getQueryClient(),
  );
  if (data !== undefined) return data;
  return isError && !isFetching ? FAILED_CATALOG : EMPTY_CATALOG;
}

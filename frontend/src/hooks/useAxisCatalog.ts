"use client";

import { useQuery } from "@tanstack/react-query";
import { getAxisCatalog } from "@/services/axisCatalogApi";
import { axisCatalogFromResponse, EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";
import { tileVersionGatedGroupLabels } from "@/lib/mapDisplay/tileVersionGated";
import { getQueryClient } from "@/lib/queryClient";
import type { FetchFailure } from "@/types/fetchFailure";
import type { AxisCatalogResponse } from "@/types/route";

const AXIS_CATALOG_QUERY_KEY = ["axis-catalog"] as const;

const FAILED_CATALOG: AxisCatalog = { ...EMPTY_CATALOG, failed: true };

/** 軸カタログの取得をやり直す（`failed`状態からの明示的な再試行導線用）。
 * 既に成功していれば何もしない。再取得中は`failed`を下ろし、UIが「取得中」へ戻る。 */
export function retryAxisCatalogFetch(): void {
  const client = getQueryClient();
  if (client.getQueryData(AXIS_CATALOG_QUERY_KEY) !== undefined) return;
  void client.refetchQueries({ queryKey: AXIS_CATALOG_QUERY_KEY });
}

const AXIS_CATALOG_FETCH_FAILURE: FetchFailure = {
  id: "axis-catalog",
  label: "評価軸の一覧",
  effect: `地図の${tileVersionGatedGroupLabels().join("・")}を表示できません。ルートは重み配分を変えていても反映できず、既定の配分で作ります。ルートの合成も使えません。`,
  onRetry: retryAxisCatalogFetch,
};

/** 軸カタログが取れていないことの項目（取れていれば・取得中なら無い）。常設ヘッダーの印と、重みタブの告知が読む。 */
export function axisCatalogFetchFailure(catalog: AxisCatalog): FetchFailure | null {
  return catalog.failed ? AXIS_CATALOG_FETCH_FAILURE : null;
}

/** 軸カタログの応答から、読み手の用途の形を導いて返す。取得は読み手の間で1つを共有し、形は読み手が決める
 * （1つの機能だけが読む形は、その機能が`select`を持つ）。マウントのたびに取り、軸スタジオで公開した軸を再デプロイ
 * なしに反映する。一度届いた応答は、後の取得の失敗で巻き戻さない。
 *
 * `select`はモジュールの関数を渡す——参照が変わるたびに導き直す。届くまで・失敗の間は`data`が`undefined`で、
 * `failed`は取得を試みて失敗し、まだ一度も成功していないことを表す。 */
export function useAxisCatalogSelect<T>(select: (response: AxisCatalogResponse) => T): {
  data: T | undefined;
  failed: boolean;
} {
  const { data, isError, isFetching } = useQuery(
    // 読み手が一時いなくなっても捨てない（捨てると、次にマウントした部品が軸0件から始まる）。
    { queryKey: AXIS_CATALOG_QUERY_KEY, queryFn: getAxisCatalog, gcTime: Infinity, select },
    getQueryClient(),
  );
  return { data, failed: data === undefined && isError && !isFetching };
}

/** 軸カタログ。届くまで・失敗したときは軸0件のカタログを返す（`loaded`・`failed`で見分ける）。
 * **重みを送るような「今の公開軸と一致していなければならない」処理は`loaded`を確かめる**——届く前の空の一覧で
 * 送ると、公開軸と食い違う重みになる。 */
export function useAxisCatalog(): AxisCatalog {
  const { data, failed } = useAxisCatalogSelect(axisCatalogFromResponse);
  if (data !== undefined) return data;
  return failed ? FAILED_CATALOG : EMPTY_CATALOG;
}

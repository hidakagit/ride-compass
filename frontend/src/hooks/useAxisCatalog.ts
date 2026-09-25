"use client";

import { useEffect, useSyncExternalStore } from "react";
import { getAxisCatalog } from "@/services/axisCatalogApi";
import { setTileVersions } from "@/services/regionApi";
import { axisCatalogFromResponse, EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";

// 複数の部品が同時にマウントしうるので、飛んでいる最中の取得だけを共有する。結果は取っておかず、後からマウントした
// 部品は改めて最新を取る（軸スタジオで公開した軸を再デプロイなしに反映する）。
let inFlightCatalogFetch: ReturnType<typeof getAxisCatalog> | null = null;

function fetchAxisCatalogDeduped(): ReturnType<typeof getAxisCatalog> {
  if (inFlightCatalogFetch) return inFlightCatalogFetch;
  const request = getAxisCatalog().finally(() => {
    if (inFlightCatalogFetch === request) inFlightCatalogFetch = null;
  });
  inFlightCatalogFetch = request;
  return request;
}

// 届いたカタログは1つのストアに置き、全部の呼び出し元が同じ参照を読む（部品ごとに軸の並びが食い違わない）。
let sharedCatalog: AxisCatalog = EMPTY_CATALOG;
const catalogListeners = new Set<() => void>();

function publishCatalog(next: AxisCatalog): void {
  sharedCatalog = next;
  catalogListeners.forEach((listener) => listener());
}

function subscribeToCatalog(listener: () => void): () => void {
  catalogListeners.add(listener);
  return () => {
    catalogListeners.delete(listener);
  };
}

function getCatalogSnapshot(): AxisCatalog {
  return sharedCatalog;
}

function getCatalogServerSnapshot(): AxisCatalog {
  return EMPTY_CATALOG;
}

function loadAxisCatalog(): void {
  fetchAxisCatalogDeduped()
    .then((response) => {
      // タイルの世代は地図のソースのURLに入るため、カタログより先に渡す。
      setTileVersions(response.tile_versions ?? {});
      publishCatalog(
        axisCatalogFromResponse(
          response.axes,
          response.material_runtime_scales ?? {},
          response.client_tuning ?? {},
          response.accident_years ?? [],
        ),
      );
    })
    .catch(() => {
      // 一度でも届いていれば、この取得の失敗で巻き戻さない。
      if (!sharedCatalog.loaded && !sharedCatalog.failed) {
        publishCatalog({ ...sharedCatalog, failed: true });
      }
    });
}

/** 軸カタログの取得をやり直す（`failed`状態からの明示的な再試行導線用）。
 * 既に成功していれば何もしない。再取得中は`failed`を下ろし、UIが「取得中」へ戻る。 */
export function retryAxisCatalogFetch(): void {
  if (sharedCatalog.loaded) return;
  publishCatalog({ ...sharedCatalog, failed: false });
  loadAxisCatalog();
}

/** 軸カタログ。マウントのたびに取り、軸スタジオで公開した軸を再デプロイなしに反映する。届くまで・失敗したときは
 * 軸0件のカタログを返す（`loaded`・`failed`で見分ける）。**重みを送るような「今の公開軸と一致していなければならない」
 * 処理は`loaded`を確かめる**——届く前の空の一覧で送ると、公開軸と食い違う重みになる。 */
export function useAxisCatalog(): AxisCatalog {
  useEffect(() => {
    loadAxisCatalog();
  }, []);

  return useSyncExternalStore(subscribeToCatalog, getCatalogSnapshot, getCatalogServerSnapshot);
}

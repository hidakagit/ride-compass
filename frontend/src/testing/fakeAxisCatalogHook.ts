/** 部品のテストが当てる`useAxisCatalog`の代役。**共有ストアを持たない**。
 *
 * 本番のフックは、同じカタログを複数の呼び出し元へ配るためにモジュールスコープの
 * ストアを持つ。部品のテストをそのまま当てると、前のテストで解決したカタログが次の
 * テストの初期表示へ残る。**そのために本番へ初期化の口を開けない**——appはテストの
 * 都合を意識した口を持たない（設計原則 構造仕様15）ので、部品側がこちらを当てる。
 *
 * 取得と導出は本物と同じものを呼ぶ（`axisCatalogFromResponse`）。ストアの振る舞い
 * （同時マウントの重複排除・後発の再取得の共有）は`useAxisCatalog`自身のテストが見る。
 *
 * **`vi.resetModules()`で画面を読み込み直す側は、この代役も貼り直すこと**（`vi.doMock`）。
 * `vi.mock`のファクトリは読み込み直しに追随しないため、貼り直さないと画面が見ているのとは
 * 別の実体へタイル世代を書き、画面側は「配信情報を取得できず」のまま固まる。
 */
import { useCallback, useEffect, useState } from "react";

import { getAxisCatalog } from "@/services/axisCatalogApi";
import { setTileVersions } from "@/services/regionApi";
import { axisCatalogFromResponse, EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";

let retry: (() => void) | null = null;

export function useFakeAxisCatalog(): AxisCatalog {
  const [catalog, setCatalog] = useState<AxisCatalog>(EMPTY_CATALOG);

  const load = useCallback(() => {
    void (async () => {
      try {
        const response = await getAxisCatalog();
        // タイル世代は地図のソースURLに入るため、カタログを公開する前に渡す。
        setTileVersions(response.tile_versions ?? {});
        setCatalog(
          axisCatalogFromResponse(
            response.axes,
            response.material_runtime_scales ?? {},
            response.client_tuning ?? {},
            response.accident_years ?? [],
          ),
        );
      } catch {
        setCatalog((current) => (current.loaded ? current : { ...current, failed: true }));
      }
    })();
  }, []);

  useEffect(() => {
    retry = () => {
      setCatalog((current) => ({ ...current, failed: false }));
      load();
    };
    load();
  }, [load]);

  return catalog;
}

export function retryFakeAxisCatalogFetch(): void {
  retry?.();
}

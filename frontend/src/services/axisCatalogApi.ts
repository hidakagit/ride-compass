import { backendApi, getOptions, requestApi } from "@/lib/apiClient";
import { CATALOG_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

// 軸カタログ取得。認可不要の読み取り専用API。軸スタジオが管理API経由でDBへ追加した軸も、
// この取得だけでフロントへ反映される。
export function getAxisCatalog() {
  return requestApi(
    (init) => backendApi.GET("/api/axis-catalog", init),
    getOptions({ timeoutMs: CATALOG_API_TIMEOUT_MS, category: "api:axisCatalog", errorLabel: "評価軸カタログ" }),
  );
}

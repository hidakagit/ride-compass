import type { AxisCatalogResponse } from "@/types/route";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { fetchJson } from "@/lib/fetchJson";

// 軸カタログ取得（改善計画T269）。認可不要の読み取り専用API。軸スタジオ（T270）が
// 管理API経由でDBへ追加した軸も、この取得だけでフロントへ反映される。
export async function getAxisCatalog(): Promise<AxisCatalogResponse> {
  const url = `${API_BASE_URL}/api/axis-catalog`;
  return fetchJson<AxisCatalogResponse>(url, {
    timeoutMs: 10000,
    category: "api:axisCatalog",
    errorLabel: "評価軸カタログ",
  });
}

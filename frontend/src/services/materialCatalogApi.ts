import type { MaterialCatalogResponse } from "@/types/route";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { fetchJson } from "@/lib/fetchJson";
import { CATALOG_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

// 材料カタログ取得。認可不要の読み取り専用API。材料の追加・変更は
// backend/app/domain/material_catalog.py側のコード変更・再デプロイのみで行い、
// GUIからは編集できない。
export async function getMaterialCatalog(): Promise<MaterialCatalogResponse> {
  const url = `${API_BASE_URL}/api/material-catalog`;
  return fetchJson<MaterialCatalogResponse>(url, {
    timeoutMs: CATALOG_API_TIMEOUT_MS,
    category: "api:materialCatalog",
    errorLabel: "材料カタログ",
  });
}

import type { MaterialCatalogResponse } from "@/types/route";
import { fetchJson } from "@/lib/fetchJson";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// 材料カタログ取得（改善計画T277）。認可不要の読み取り専用API。材料の追加・変更は
// backend/app/domain/material_catalog.py側のコード変更・再デプロイのみで行い、
// GUIからは編集できない（ユーザー方針）。
export async function getMaterialCatalog(): Promise<MaterialCatalogResponse> {
  const url = `${API_BASE_URL}/api/material-catalog`;
  return fetchJson<MaterialCatalogResponse>(url, {
    timeoutMs: 10000,
    category: "api:materialCatalog",
    errorLabel: "材料カタログ",
  });
}

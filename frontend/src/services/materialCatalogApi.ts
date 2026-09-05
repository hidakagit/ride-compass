import type { MaterialCatalogResponse, MaterialValuesResponse } from "@/types/route";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { fetchJson } from "@/lib/fetchJson";

// 材料カタログ取得。認可不要の読み取り専用API。材料の追加・変更は
// backend/app/domain/material_catalog.py側のコード変更・再デプロイのみで行い、
// GUIからは編集できない。
export async function getMaterialCatalog(): Promise<MaterialCatalogResponse> {
  const url = `${API_BASE_URL}/api/material-catalog`;
  return fetchJson<MaterialCatalogResponse>(url, {
    timeoutMs: 10000,
    category: "api:materialCatalog",
    errorLabel: "材料カタログ",
  });
}

// 材料の実データ値一覧取得。highway/surface/smoothnessのように
// OSMタグの生値でオープンエンドな材料向け。認可不要の読み取り専用API。未知の材料idは
// 404（fetchJsonがエラーとしてrejectする）、既知だが動的値一覧に対応していない材料・
// DB未接続・DB障害はいずれも`{values: []}`（200）を返す（呼び出し側は空配列を
// 「動的値一覧が使えない」の合図として自由テキスト入力へフォールバックする）。
export async function getMaterialValues(materialId: string): Promise<MaterialValuesResponse> {
  const url = `${API_BASE_URL}/api/material-catalog/${encodeURIComponent(materialId)}/values`;
  return fetchJson<MaterialValuesResponse>(url, {
    timeoutMs: 10000,
    category: "api:materialValues",
    errorLabel: "材料の値一覧",
  });
}

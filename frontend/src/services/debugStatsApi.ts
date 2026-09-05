import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { fetchJson } from "@/lib/fetchJson";
import type { components } from "@/types/generated/api";

// APIの型はbackendのOpenAPIスキーマから生成した generated/api.d.ts を正とし、
// このファイルは再エクスポートのみを持つ（手書きの二重管理をしない）。
// backend/app/api/routers/health.py: DebugStatsResponse/ExternalCallStatsResponse
// （infrastructure/debug_log.py: get_stats()が組み立てるdictの構造）が単一の情報源。
// backend側のレスポンスモデルを変更したら
// backend/scripts/export_openapi.py → npm run generate:api で生成物を更新すること
// （CIのapi-contractジョブがドリフトを検知する）。
type Schemas = components["schemas"];

// カテゴリはbackend/app/infrastructure/debug_log.pyのlog_external_call呼び出し元
// （weather:open-meteo・basemap:openfreemap・region:road-surface-tile等）に対応する。
export type ExternalCallStats = Schemas["ExternalCallStatsResponse"];
export type DebugStats = Schemas["DebugStatsResponse"];

export async function getDebugStats(): Promise<DebugStats> {
  return fetchJson<DebugStats>(`${API_BASE_URL}/api/debug/stats`, {
    timeoutMs: 5000,
    category: "api:debug-stats",
    errorLabel: "システム状況",
  });
}

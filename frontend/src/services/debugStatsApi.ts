import { debugLog } from "@/lib/debugLog";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ExternalCallStats {
  calls: number;
  errors: number;
  cache_hits: number;
  cache_misses: number;
  total_ms: number;
  max_ms: number;
  avg_ms: number;
  cache_hit_rate: number | null;
}

// backend/app/api/routers/health.py: debug_stats のレスポンス形状。
// カテゴリはbackend/app/infrastructure/debug_log.pyのlog_external_call呼び出し元
// （weather:open-meteo・basemap:openfreemap・region:road-surface-tile等）に対応する。
export interface DebugStats {
  commit: string | null;
  started_at: string;
  engine: string;
  debug_mode: boolean;
  external: Record<string, ExternalCallStats>;
  rate_limit_rejections: Record<string, number>;
}

export async function getDebugStats(): Promise<DebugStats> {
  const startedAt = performance.now();
  debugLog("api:debug-stats", "リクエスト開始");
  const response = await fetch(`${API_BASE_URL}/api/debug/stats`, { signal: AbortSignal.timeout(5000) });
  const durationMs = Math.round(performance.now() - startedAt);

  if (!response.ok) {
    debugLog("api:debug-stats", `失敗 (HTTP ${response.status})`, { durationMs }, "error");
    throw new Error(`システム状況の取得に失敗しました（HTTP ${response.status}）`);
  }

  let data: DebugStats;
  try {
    data = await response.json();
  } catch {
    debugLog("api:debug-stats", "失敗 (不正なレスポンス)", { durationMs }, "error");
    throw new Error("システム状況の解析に失敗しました");
  }
  debugLog("api:debug-stats", "成功", { durationMs });
  return data;
}

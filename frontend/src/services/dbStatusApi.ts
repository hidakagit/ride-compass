import type { DbStatusResponse, RoadGraphTilesResponse } from "@/types/route";
import { fetchJson } from "@/lib/fetchJson";
import {
  DEFAULT_API_TIMEOUT_MS,
  HEAVY_ADMIN_API_TIMEOUT_MS,
} from "@/lib/apiTimeouts";

// 本番DBの状態（backend GET /api/admin/db-status、Basic認証必須）のクライアント。
// derivedDataFreshnessApi.tsと同じく同一オリジンのroute handlerを経由し、/adminページの
// ブラウザ標準Basic認証セッションをそのまま再利用する。

const API_PATH = "/admin/api/db-status";

export async function getDbStatus(): Promise<DbStatusResponse> {
  return fetchJson<DbStatusResponse>(API_PATH, {
    timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS,
    category: "api:dbStatus",
    errorLabel: "DB状態",
  });
}

// split済みタイル（backend GET /api/admin/road-graph-tiles）。地図を開いたときだけ呼ぶ
// ——本番では全域ぶんの件数になるため、DB状態の集計と一緒には運ばない。
export async function getRoadGraphTiles(): Promise<RoadGraphTilesResponse> {
  return fetchJson<RoadGraphTilesResponse>("/admin/api/road-graph-tiles", {
    timeoutMs: DEFAULT_API_TIMEOUT_MS,
    category: "api:roadGraphTiles",
    errorLabel: "split済みタイル",
  });
}

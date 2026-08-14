import { debugLog } from "@/lib/debugLog";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ROAD_SURFACE_TILE_PATH = "/api/region/road-surface-tiles/{z}/{x}/{y}.pbf";

// 路面の地域レイヤー（Step10）のベクタタイルURL。基礎地図タイルと同じ理由でフロントエンド
// 自身のオリジン（Next.jsのrewrites経由でバックエンドにプロキシ）を使う。ベクタタイルの
// 取得はMapLibreがWeb Worker内で行うため、相対パスのままだと「ページのオリジンに対して
// 解決する」というラスタタイル（Image要素の読み込み、メインスレッド）の挙動が通用せず、
// URLの構築に失敗することを実機確認した。window.location.originで明示的に絶対URL化する
// 必要があるため、モジュール読み込み時ではなく呼び出し時（クライアントサイドのみ）に
// 評価する関数として提供する。
export function roadSurfaceTileUrl(): string {
  return `${window.location.origin}${ROAD_SURFACE_TILE_PATH}`;
}

// バックエンド（domain/region.py）のROAD_TILE_MIN_ZOOM/MAX_ZOOMと一致させる。
export const ROAD_TILE_MIN_ZOOM = 12;
export const ROAD_TILE_MAX_ZOOM = 15;

export async function refreshBasemapCache(): Promise<void> {
  const startedAt = performance.now();
  debugLog("api:basemap-refresh", "リクエスト開始");
  const response = await fetch(`${API_BASE_URL}/api/basemap/refresh`, { method: "POST" });
  debugLog("api:basemap-refresh", response.ok ? "成功" : `失敗 (HTTP ${response.status})`, {
    durationMs: Math.round(performance.now() - startedAt),
    // サーバーログとの突き合わせ用リクエストID(routeApi.tsと同じ扱い)
    requestId: response.headers.get("x-request-id"),
  });
}

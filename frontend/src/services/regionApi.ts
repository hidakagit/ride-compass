import { debugLog } from "@/lib/debugLog";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ROAD_SURFACE_TILE_PATH = "/api/region/road-surface-tiles/{z}/{x}/{y}.pbf";

// タイル内容の世代。タイルへ焼き込むプロパティが増えた（内容の互換性が変わった）ときに
// 上げると、URLが変わることでブラウザHTTPキャッシュ（Cache-Control: max-age=3600）に残る
// 旧世代タイルを踏まなくなる。バックエンドのファイルキャッシュ側の世代
// （region_service.pyの_tile_cache_path）と対で更新すること。
// v2: surface（正規化済み生タグ）・highwayプロパティ追加（色分けモード用）。
const ROAD_SURFACE_TILE_VERSION = "2";

// 路面の地域レイヤー（Step10）のベクタタイルURL。基礎地図タイルと同じ理由でフロントエンド
// 自身のオリジン（Next.jsのrewrites経由でバックエンドにプロキシ）を使う。ベクタタイルの
// 取得はMapLibreがWeb Worker内で行うため、相対パスのままだと「ページのオリジンに対して
// 解決する」というラスタタイル（Image要素の読み込み、メインスレッド）の挙動が通用せず、
// URLの構築に失敗することを実機確認した。window.location.originで明示的に絶対URL化する
// 必要があるため、モジュール読み込み時ではなく呼び出し時（クライアントサイドのみ）に
// 評価する関数として提供する。
export function roadSurfaceTileUrl(): string {
  return `${window.location.origin}${ROAD_SURFACE_TILE_PATH}?v=${ROAD_SURFACE_TILE_VERSION}`;
}

// バックエンド（domain/region.py）のROAD_TILE_MIN_ZOOM/MAX_ZOOMと一致させる。
export const ROAD_TILE_MIN_ZOOM = 12;
export const ROAD_TILE_MAX_ZOOM = 15;

export async function refreshBasemapCache(): Promise<void> {
  const startedAt = performance.now();
  debugLog("api:basemap-refresh", "リクエスト開始");
  // 以前はtry/catchも!response.okのチェックも無く、ネットワークエラー時は
  // 未処理のPromise rejectionになり、失敗時に呼び出し元(MapView.tsx)へ何も伝わらず
  // 「変わらないデータを更新」ボタンが無反応に見えていた。
  try {
    const response = await fetch(`${API_BASE_URL}/api/basemap/refresh`, {
      method: "POST",
      signal: AbortSignal.timeout(15000),
    });
    const durationMs = Math.round(performance.now() - startedAt);
    const requestId = response.headers.get("x-request-id");
    debugLog("api:basemap-refresh", response.ok ? "成功" : `失敗 (HTTP ${response.status})`, {
      durationMs,
      requestId,
    });
    if (!response.ok) {
      throw new Error(`地図キャッシュの更新に失敗しました（HTTP ${response.status}）`);
    }
  } catch (error) {
    debugLog("api:basemap-refresh", "失敗 (通信エラー)", {
      durationMs: Math.round(performance.now() - startedAt),
      error: error instanceof Error ? error.message : String(error),
    });
    throw error instanceof Error ? error : new Error("地図キャッシュの更新に失敗しました");
  }
}

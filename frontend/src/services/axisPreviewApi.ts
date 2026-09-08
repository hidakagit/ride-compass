import type { ValueDistribution } from "@/components/AxisStudio/scoreDistribution";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

// 軸スタジオの分布プレビュー（backend/app/services/axis_preview_service.py）のクライアント。
// axisAdminApi.tsと同じく同一オリジンのNext.js route handler経由で、Basic認証情報は
// ブラウザの認証キャッシュから自動付与される。
//
// 初回はWayの抽選と材料の組み立てを伴うためbackend側で1秒前後かかる（2回目以降は
// サーバー側のキャッシュに当たる）。編集の手応えを損なわないよう、呼び出し側が
// デバウンスしてから呼ぶ前提。

const PREVIEW_TIMEOUT_MS = 60000;

export interface MaterialDistribution extends ValueDistribution {
  available: boolean;
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const startedAt = performance.now();
  let response: Response;
  try {
    response = await fetch(path, { ...init, signal: AbortSignal.timeout(PREVIEW_TIMEOUT_MS) });
  } catch (error) {
    debugLog("api:axisPreview", "失敗 (通信エラー)", { path, error: String(error) }, "error");
    throw new Error("分布の取得に失敗しました（通信エラー）");
  }
  const durationMs = Math.round(performance.now() - startedAt);
  if (!response.ok) {
    debugLog("api:axisPreview", `失敗 (HTTP ${response.status})`, { path, durationMs }, "error");
    const body = await response.json().catch(() => null);
    const detail = formatErrorDetail((body as { detail?: unknown } | null)?.detail);
    throw new Error(detail ?? `分布の取得に失敗しました（HTTP ${response.status}）`);
  }
  debugLog("api:axisPreview", "成功", { path, durationMs });
  return (await response.json()) as T;
}

/** 編集中のshapeで、折れ点を通す前の生値がどう分布するかを取る。 */
export async function fetchAxisValueDistribution(shape: unknown): Promise<ValueDistribution> {
  return getJson<ValueDistribution>("/admin/api/axis-definitions/preview-distribution", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shape }),
  });
}

/** 1材料の値が実データでどの範囲に散らばっているかを取る。 */
export async function fetchMaterialDistribution(materialId: string): Promise<MaterialDistribution> {
  return getJson<MaterialDistribution>(
    `/admin/api/material-distribution/${encodeURIComponent(materialId)}`,
  );
}

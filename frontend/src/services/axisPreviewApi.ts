import type { ValueDistribution } from "@/components/AxisStudio/scoreDistribution";
import { requestJson } from "@/lib/fetchJson";
import { DEFAULT_API_TIMEOUT_MS, DISTRIBUTION_API_TIMEOUT_MS } from "@/lib/apiTimeouts";
import type { components } from "@/types/generated/api";

// 軸スタジオの分布プレビュー（backend/app/services/axis_preview_service.py）のクライアント。
// axisAdminApi.tsと同じく同一オリジンのNext.js route handler経由で、Basic認証情報は
// ブラウザの認証キャッシュから自動付与される。
//
// 初回はWayの抽選と材料の組み立てを伴うためbackend側で1秒前後かかる（2回目以降は
// サーバー側のキャッシュに当たる）。編集の手応えを損なわないよう、呼び出し側が
// デバウンスしてから呼ぶ前提。

export interface MaterialDistribution extends ValueDistribution {
  available: boolean;
}

const DISTRIBUTION_MESSAGES = {
  failure: "分布の取得に失敗しました",
  parseFailure: "分布の解析に失敗しました",
};

/** 編集中のshapeで、折れ点を通す前の生値がどう分布するかを取る。 */
export async function fetchAxisValueDistribution(shape: unknown): Promise<ValueDistribution> {
  return requestJson<ValueDistribution>("/admin/api/axis-definitions/preview-distribution", {
    method: "POST",
    body: { shape },
    timeoutMs: DISTRIBUTION_API_TIMEOUT_MS,
    category: "api:axisPreview",
    messages: DISTRIBUTION_MESSAGES,
  });
}

export type DisplayThresholdsPreviewRequest = components["schemas"]["DisplayThresholdsPreviewRequest"];

/** 編集中の軸で、人が刻んだ段の境界のうち地図では段にならないものを取る。判定はbackendが
 * 地図の段を作るのと同じ関数で行う。DBを読まないため既定のタイムアウトで足りる。 */
export async function fetchThresholdsDroppedOnMap(body: DisplayThresholdsPreviewRequest): Promise<number[]> {
  const response = await requestJson<components["schemas"]["DisplayThresholdsPreviewResponse"]>(
    "/admin/api/axis-definitions/preview-display-thresholds",
    {
      method: "POST",
      body,
      timeoutMs: DEFAULT_API_TIMEOUT_MS,
      category: "api:axisPreview",
      messages: { failure: "しきい値の確認に失敗しました", parseFailure: "しきい値の確認結果を解析できませんでした" },
    },
  );
  return response.dropped_on_map;
}

/** 1材料の値が実データでどの範囲に散らばっているかを取る。 */
export async function fetchMaterialDistribution(materialId: string): Promise<MaterialDistribution> {
  return requestJson<MaterialDistribution>(`/admin/api/material-distribution/${encodeURIComponent(materialId)}`, {
    timeoutMs: DISTRIBUTION_API_TIMEOUT_MS,
    category: "api:axisPreview",
    messages: DISTRIBUTION_MESSAGES,
  });
}

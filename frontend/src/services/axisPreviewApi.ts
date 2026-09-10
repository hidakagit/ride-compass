import type { ValueDistribution } from "@/components/AxisStudio/scoreDistribution";
import { requestJson } from "@/lib/fetchJson";
import { DISTRIBUTION_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

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

/** 1材料の値が実データでどの範囲に散らばっているかを取る。 */
export async function fetchMaterialDistribution(materialId: string): Promise<MaterialDistribution> {
  return requestJson<MaterialDistribution>(
    `/admin/api/material-distribution/${encodeURIComponent(materialId)}`,
    {
      timeoutMs: DISTRIBUTION_API_TIMEOUT_MS,
      category: "api:axisPreview",
      messages: DISTRIBUTION_MESSAGES,
    },
  );
}

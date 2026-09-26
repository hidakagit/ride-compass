"use client";

// 軸スタジオで編集中の折れ点が、値それぞれに何点を付けるか（分布の階級の代表値・材料の参考点）を取得する。
// 点数の計算はbackendが持つ（評価と同じ`BreakpointLinearShape.score_at`）。

import { fetchScoresPreview, type ScoresPreview, type ScoresPreviewRequest } from "@/features/admin/adminApi";
import { useSettledDraftQuery } from "@/features/admin/useSettledDraftQuery";

/** `request`がnullの間は問い合わせない。入力を変えた直後・取得に失敗したときはnull——前の折れ点の
 * 点数を今の折れ点のものとして出さない。 */
export function useScoresPreview(request: ScoresPreviewRequest | null): ScoresPreview | null {
  return useSettledDraftQuery("scores-preview", request, fetchScoresPreview) ?? null;
}

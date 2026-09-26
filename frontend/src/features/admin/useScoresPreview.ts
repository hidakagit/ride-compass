"use client";

// 軸スタジオで編集中の折れ点が、値それぞれに何点を付けるか（分布の階級の代表値・材料の参考点）を取得する。
// 点数の計算はbackendが持ち（評価と同じ`BreakpointLinearShape.score_at`）、ここは下書きが落ち着いたら
// 問い合わせて結果を返すだけ。

import { useQuery } from "@tanstack/react-query";

import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";
import { fetchScoresPreview, type ScoresPreview, type ScoresPreviewRequest } from "@/features/admin/adminApi";
import { getQueryClient } from "@/lib/queryClient";

/** `request`がnullの間は問い合わせない。入力を変えた直後・取得に失敗したときはnull——前の折れ点の
 * 点数を今の折れ点のものとして出さない。 */
export function useScoresPreview(request: ScoresPreviewRequest | null): ScoresPreview | null {
  const key = request === null ? "" : JSON.stringify(request);
  const debouncedKey = useDebouncedValue(key, MAP_FETCH_DEBOUNCE_MS);
  const { data } = useQuery(
    {
      queryKey: ["scores-preview", debouncedKey],
      queryFn: () => fetchScoresPreview(JSON.parse(debouncedKey) as ScoresPreviewRequest),
      enabled: debouncedKey !== "",
    },
    getQueryClient(),
  );

  return debouncedKey === key && data !== undefined ? data : null;
}

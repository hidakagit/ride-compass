"use client";

// 軸スタジオで編集中の折れ点が、値それぞれに何点を付けるか（分布の階級の代表値・材料の参考点）を取得する。
// 点数の計算はbackendが持ち（評価と同じ`BreakpointLinearShape.score_at`）、ここは下書きが落ち着いたら
// 問い合わせて結果を返すだけ。

import { useEffect, useRef, useState } from "react";

import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";
import { fetchScoresPreview, type ScoresPreview, type ScoresPreviewRequest } from "@/features/admin/adminApi";

/** `request`がnullの間は問い合わせない。入力を変えた直後・取得に失敗したときはnull——前の折れ点の
 * 点数を今の折れ点のものとして出さない。 */
export function useScoresPreview(request: ScoresPreviewRequest | null): ScoresPreview | null {
  const [result, setResult] = useState<{ key: string; preview: ScoresPreview | null }>({ key: "", preview: null });
  const key = request === null ? "" : JSON.stringify(request);
  const debouncedKey = useDebouncedValue(key, MAP_FETCH_DEBOUNCE_MS);
  const seqRef = useRef(0);

  useEffect(() => {
    if (!debouncedKey) return;
    const seq = ++seqRef.current;
    fetchScoresPreview(JSON.parse(debouncedKey) as ScoresPreviewRequest)
      .then((preview) => {
        if (seq === seqRef.current) setResult({ key: debouncedKey, preview });
      })
      .catch(() => {
        if (seq === seqRef.current) setResult({ key: debouncedKey, preview: null });
      });
  }, [debouncedKey]);

  return result.key === key ? result.preview : null;
}

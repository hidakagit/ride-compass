"use client";

// 軸スタジオで刻んだ段の境界のうち、地図では段にならないものを取得する。判定はbackendが
// 持ち（`domain/axis_display.py: thresholds_the_map_drops`）、ここは下書きが落ち着いたら
// 問い合わせて結果を返すだけ。

import { useEffect, useRef, useState } from "react";

import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";
import { fetchThresholdsDroppedOnMap, type DisplayThresholdsPreviewRequest } from "@/services/axisPreviewApi";

const NONE: readonly number[] = [];

/** `request`がnull（しきい値を上書きしていない）の間は問い合わせない。取得に失敗したときは
 * 印を出さない——判定できないことを「効かない値がある」と取り違えさせないため。 */
export function useThresholdsDroppedOnMap(request: DisplayThresholdsPreviewRequest | null): readonly number[] {
  const [result, setResult] = useState<{ key: string; dropped: readonly number[] }>({ key: "", dropped: NONE });
  const key = request === null ? "" : JSON.stringify(request);
  const debouncedKey = useDebouncedValue(key, MAP_FETCH_DEBOUNCE_MS);
  const seqRef = useRef(0);

  useEffect(() => {
    if (!debouncedKey) return;
    const seq = ++seqRef.current;
    fetchThresholdsDroppedOnMap(JSON.parse(debouncedKey) as DisplayThresholdsPreviewRequest)
      .then((dropped) => {
        if (seq === seqRef.current) setResult({ key: debouncedKey, dropped });
      })
      .catch(() => {
        if (seq === seqRef.current) setResult({ key: debouncedKey, dropped: NONE });
      });
  }, [debouncedKey]);

  // 入力を変えた直後は、前の入力に対する結果を出さない。
  return result.key === key ? result.dropped : NONE;
}

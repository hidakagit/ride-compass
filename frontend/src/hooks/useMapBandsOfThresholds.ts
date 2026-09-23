"use client";

// 軸スタジオで刻んだ段の境界が、地図でどの段になるか（段にならない境界と、地図に残る段）を
// 取得する。判定はbackendが持ち（`domain/axis_display.py: bands_the_map_keeps`）、ここは
// 下書きが落ち着いたら問い合わせて結果を返すだけ。

import { useEffect, useRef, useState } from "react";

import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";
import {
  fetchMapBandsOfThresholds,
  type DisplayThresholdsPreviewRequest,
  type MapBandsOfThresholds,
} from "@/services/axisPreviewApi";

/** 判定が無い間の値。入力どおりの段で出す（落ちる値なし・全段が残る）。 */
export const NO_MAP_BANDS_JUDGEMENT: MapBandsOfThresholds = { droppedOnMap: [], bandsOnMap: null };

/** `request`がnull（しきい値を上書きしていない）の間は問い合わせない。取得に失敗したときは
 * 印を出さない——判定できないことを「効かない値がある」と取り違えさせないため。 */
export function useMapBandsOfThresholds(request: DisplayThresholdsPreviewRequest | null): MapBandsOfThresholds {
  const [result, setResult] = useState<{ key: string; bands: MapBandsOfThresholds }>({
    key: "",
    bands: NO_MAP_BANDS_JUDGEMENT,
  });
  const key = request === null ? "" : JSON.stringify(request);
  const debouncedKey = useDebouncedValue(key, MAP_FETCH_DEBOUNCE_MS);
  const seqRef = useRef(0);

  useEffect(() => {
    if (!debouncedKey) return;
    const seq = ++seqRef.current;
    fetchMapBandsOfThresholds(JSON.parse(debouncedKey) as DisplayThresholdsPreviewRequest)
      .then((bands) => {
        if (seq === seqRef.current) setResult({ key: debouncedKey, bands });
      })
      .catch(() => {
        if (seq === seqRef.current) setResult({ key: debouncedKey, bands: NO_MAP_BANDS_JUDGEMENT });
      });
  }, [debouncedKey]);

  // 入力を変えた直後は、前の入力に対する結果を出さない。
  return result.key === key ? result.bands : NO_MAP_BANDS_JUDGEMENT;
}

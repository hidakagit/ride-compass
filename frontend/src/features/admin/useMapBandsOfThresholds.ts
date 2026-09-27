"use client";

// 軸スタジオで刻んだ段の境界が、地図でどの段になるか（段にならない境界と、地図に残る段）を
// 取得する。判定はbackendが持つ（`domain/axis_display.py: bands_the_map_keeps`）。

import {
  fetchMapBandsOfThresholds,
  type DisplayThresholdsPreviewRequest,
  type MapBandsOfThresholds,
} from "@/features/admin/adminApi";
import { useSettledDraftQuery } from "@/features/admin/useSettledDraftQuery";

/** 判定と、今の入力の判定を取れなかったか。 */
export interface MapBandsJudgement extends MapBandsOfThresholds {
  failed: boolean;
}

/** 判定が無い間の値。入力どおりの段で出す（落ちる値なし・全段が残る）。 */
export const NO_MAP_BANDS_JUDGEMENT: MapBandsJudgement = { droppedOnMap: [], bandsOnMap: null, failed: false };

/** `request`がnull（しきい値を上書きしていない）の間は問い合わせない。取得に失敗したときは印を出さない——判定
 * できないことを「効かない値がある」と取り違えさせないため。失敗したことは`failed`で返す（入力どおりの段が地図の
 * 段と違いうることを、呼ぶ側が添えられるように）。 */
export function useMapBandsOfThresholds(request: DisplayThresholdsPreviewRequest | null): MapBandsJudgement {
  const { data, failed } = useSettledDraftQuery("map-bands-of-thresholds", request, fetchMapBandsOfThresholds);
  if (data !== undefined) return { ...data, failed: false };
  return failed ? { ...NO_MAP_BANDS_JUDGEMENT, failed: true } : NO_MAP_BANDS_JUDGEMENT;
}

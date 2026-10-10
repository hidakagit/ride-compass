import { useState } from "react";

interface UseRouteFormSubmitOptions {
  /** 全長の目標を決めているか。 */
  distanceTargeted: boolean;
  waypointCount: number;
  /** 目的地を置いてあるか。 */
  destinationSet: boolean;
  /** 出発地が実際の位置か（現在地を取れたか、地図で置いたか）。偽の間の出発地は決まった仮の地点で、そこから
   * 作ったルートは利用者のいる場所と関係が無い。 */
  originKnown: boolean;
}

interface UseRouteFormSubmitResult {
  /** 生成できない理由（出発地が分からない・全長の目標も経由地・目的地も無く作るものが無い）。生成結果の失敗と同じ場所
   * （「ルート結果」欄）へ出す——押した場所とは別のどこかに出ると見落とすため。 */
  error: string | null;
  /** 検証し、通ったかを返す。通らなければ理由を`error`に置く。 */
  check: () => boolean;
}

/** 「ルート生成」ボタン（page.tsxの「ルート設定」見出し行）から呼ぶ検証。距離・候補数は確かめない——
 * 入力がスライダー・ステッパーで、保存値も読むときに範囲の外を捨てる（`features/route/useGenerationConditions.ts`）ので、
 * 範囲の外の値は作れない。 */
export function useRouteFormSubmit({
  distanceTargeted,
  waypointCount,
  destinationSet,
  originKnown,
}: UseRouteFormSubmitOptions): UseRouteFormSubmitResult {
  const [error, setError] = useState<string | null>(null);

  function check() {
    if (!originKnown) {
      setError("現在地が分かりません。位置情報を許可するか、「出発地を地図で選ぶ」を押して地図をタップしてください。");
      return false;
    }
    if (!distanceTargeted && waypointCount === 0 && !destinationSet) {
      setError("「全長の目標を決める」を押すか、経由地・目的地を置いてください。");
      return false;
    }
    setError(null);
    return true;
  }

  return { error, check };
}

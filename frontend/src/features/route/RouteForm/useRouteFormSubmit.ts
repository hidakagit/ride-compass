import { useState } from "react";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

export type RouteMode = "loop" | "destination";

/** 候補数の指定を使わない生成なら、backendが返す決まった候補数。指定を使うならnull。
 * 経由地を伴う目的地ルートは、backendが候補数の指定を使わず決まった数を返す
 * （`route_generator.py: applied_max_routes`、数は生成物から）。入力欄の表示・送る値・
 * 「条件が変わった」の比較は、どれもこの関数で揃える。 */
export function fixedRouteCount(routeMode: RouteMode, waypointCount: number): number | null {
  return routeMode === "destination" && waypointCount > 0 ? routeGenerateConfig.routes_with_waypoints : null;
}

interface UseRouteFormSubmitOptions {
  distance: string;
  routeMode: RouteMode;
  waypointCount: number;
  /** 目的地を置いてあるか。 */
  destinationSet: boolean;
  /** 出発地が実際の位置か（現在地を取れたか、地図で置いたか）。偽の間の出発地は決まった仮の地点で、そこから
   * 作ったルートは利用者のいる場所と関係が無い。 */
  originKnown: boolean;
}

interface UseRouteFormSubmitResult {
  /** 生成できない理由（出発地が分からない・目的地モードで地点が1つも無い）。生成結果の失敗と同じ場所
   * （「ルート結果」欄）へ出す——押した場所とは別のどこかに出ると見落とすため。 */
  error: string | null;
  /** 検証し、通れば送る距離（km）を返す。通らなければ理由を`error`に置いてnullを返す。 */
  check: () => number | null;
}

/** 「ルート生成」ボタン（page.tsxの「ルート設定」見出し行）から呼ぶ検証。距離・候補数は確かめない——
 * 入力がスライダー・ステッパーで、保存値も読むときに範囲の外を捨てる（`features/route/useGenerationConditions.ts`）ので、
 * 範囲の外の値は作れない。 */
export function useRouteFormSubmit({
  distance,
  routeMode,
  waypointCount,
  destinationSet,
  originKnown,
}: UseRouteFormSubmitOptions): UseRouteFormSubmitResult {
  const [error, setError] = useState<string | null>(null);

  function check() {
    if (!originKnown) {
      setError("現在地が分かりません。位置情報を許可するか、出発地の「地図で選ぶ」を押して地図をタップしてください。");
      return null;
    }
    if (routeMode === "destination" && waypointCount === 0 && !destinationSet) {
      setError("地図をタップして目的地か経由地を指定してください。");
      return null;
    }
    setError(null);
    // 目的地モードの距離は送らない（探索の範囲はbackendが置いた点から決める。`features/route/useRouteGeneration.ts`）。
    return routeMode === "destination" ? 0 : Number(distance);
  }

  return { error, check };
}

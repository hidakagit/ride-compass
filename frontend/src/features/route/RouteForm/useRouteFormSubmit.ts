import { useState } from "react";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

export type RouteMode = "loop" | "destination";

// backend/app/api/routers/routes.py: RouteGenerateRequest.distance_km（Field(gt=0,
// le=MAX_ROUTE_DISTANCE_KM)）と一致させる。backend側の唯一の情報源
// （export_openapi.py: ROUTE_GENERATE_CONFIG_PATH）から導出する。
const MAX_DISTANCE_KM = routeGenerateConfig.max_distance_km;
// backend/app/api/routers/routes.py: RouteGenerateRequest.max_routes（Field(ge=1,
// le=MAX_ROUTES)）と一致させる。距離入力と同じくハードコードせずroute-generate-config.jsonを
// 唯一の情報源にする。
const MAX_ROUTES = routeGenerateConfig.max_routes;

/** 候補数の指定を使わない生成なら、backendが返す決まった候補数。指定を使うならnull。
 * 経由地を伴う目的地ルートは、backendが候補数の指定を使わず決まった数を返す
 * （`route_generator.py: applied_max_routes`、数は生成物から）。入力欄の表示・検証・
 * 送る値・「条件が変わった」の比較は、どれもこの関数で揃える。 */
export function fixedRouteCount(routeMode: RouteMode, waypointCount: number): number | null {
  return routeMode === "destination" && waypointCount > 0 ? routeGenerateConfig.routes_with_waypoints : null;
}

interface UseRouteFormSubmitOptions {
  distance: string;
  maxRoutes: string;
  routeMode: RouteMode;
  waypointCount: number;
  /** 目的地を置いてあるか。 */
  destinationSet: boolean;
  onGenerate: (distanceKm: number) => void;
}

interface UseRouteFormSubmitResult {
  /** 検証エラー（距離・候補件数・目的地未指定）。生成結果の失敗と同じ場所
   * （「ルート結果」欄）へ出す——押した場所とは別のどこかに出ると見落とすため。 */
  error: string | null;
  handleSubmit: () => void;
}

// 「ルート生成」ボタン（page.tsxの「ルート設定」見出し行へ移設、RouteForm.tsxの
// タブとは別位置）から呼ぶ検証・送信ロジック。距離・候補件数の入力手段がスライダー/
// ステッパーになり範囲外の値を作れなくなったが、目的地モードの「地点未指定」は
// 引き続き発生しうるため検証自体は残す。
export function useRouteFormSubmit({
  distance,
  maxRoutes,
  routeMode,
  waypointCount,
  destinationSet,
  onGenerate,
}: UseRouteFormSubmitOptions): UseRouteFormSubmitResult {
  const [error, setError] = useState<string | null>(null);
  const maxRoutesRelevant = fixedRouteCount(routeMode, waypointCount) === null;

  function validateMaxRoutes(): boolean {
    const maxRoutesValue = Number(maxRoutes);
    if (maxRoutes.trim() === "" || Number.isNaN(maxRoutesValue) || !Number.isInteger(maxRoutesValue)) {
      setError("候補数は整数で入力してください。");
      return false;
    }
    if (maxRoutesValue < 1 || maxRoutesValue > MAX_ROUTES) {
      setError(`候補数は1〜${MAX_ROUTES}件で入力してください。`);
      return false;
    }
    return true;
  }

  function handleSubmit() {
    if (routeMode === "destination") {
      // 経由地・目的地のいずれも未指定のサイレント失敗を防ぐ。
      if (waypointCount === 0 && !destinationSet) {
        setError("地図をタップして目的地か経由地を指定してください。");
        return;
      }
      if (maxRoutesRelevant && !validateMaxRoutes()) {
        return;
      }
      // distanceはpage.tsx側が地図上の点から自動算出する（handleGenerate参照）。
      setError(null);
      onGenerate(0);
      return;
    }
    const value = Number(distance);
    if (distance.trim() === "" || Number.isNaN(value)) {
      setError("距離は数値で入力してください。");
      return;
    }
    if (value <= 0) {
      setError("距離は0より大きい値を入力してください。");
      return;
    }
    if (value > MAX_DISTANCE_KM) {
      setError(`距離は${MAX_DISTANCE_KM}km以下で入力してください。`);
      return;
    }
    if (!validateMaxRoutes()) {
      return;
    }
    setError(null);
    onGenerate(value);
  }

  return { error, handleSubmit };
}

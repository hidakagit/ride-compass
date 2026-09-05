import { useState } from "react";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { DestinationButtonState, RouteMode } from "./RouteForm";

// backend/app/api/routers/routes.py: RouteGenerateRequest.distance_km（Field(gt=0,
// le=MAX_ROUTE_DISTANCE_KM)）と一致させる。backend側の唯一の情報源
// （export_openapi.py: ROUTE_GENERATE_CONFIG_PATH）から導出する。
const MAX_DISTANCE_KM = routeGenerateConfig.max_distance_km;
// backend/app/api/routers/routes.py: RouteGenerateRequest.max_routes（Field(ge=1,
// le=MAX_ROUTES)）と一致させる。距離入力と同じくハードコードせずroute-generate-config.jsonを
// 唯一の情報源にする。
const MAX_ROUTES = routeGenerateConfig.max_routes;

/** 候補件数は周回モード、または経由地の無い目的地モードのときだけ生成結果へ反映される
 * （経由地を伴う目的地ルートはbackendが常に1件へ固定し無視する）。入力欄の表示・検証は
 * この条件で揃える（RouteForm.tsx・useRouteFormSubmit.tsの両方が使う単一の情報源）。 */
export function isMaxRoutesRelevant(routeMode: RouteMode, waypointCount: number): boolean {
  return routeMode === "loop" || waypointCount === 0;
}

export interface UseRouteFormSubmitOptions {
  distance: string;
  maxRoutes: string;
  routeMode: RouteMode;
  waypointCount: number;
  destinationState: DestinationButtonState;
  onGenerate: (distanceKm: number) => void;
}

export interface UseRouteFormSubmitResult {
  /** 検証エラー（距離・候補件数・目的地未指定）。「ルート生成」ボタンの近く
   * （page.tsx: renderRouteSectionBody）へ表示する。 */
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
  destinationState,
  onGenerate,
}: UseRouteFormSubmitOptions): UseRouteFormSubmitResult {
  const [error, setError] = useState<string | null>(null);
  const maxRoutesRelevant = isMaxRoutesRelevant(routeMode, waypointCount);

  function validateMaxRoutes(): boolean {
    const maxRoutesValue = Number(maxRoutes);
    if (maxRoutes.trim() === "" || Number.isNaN(maxRoutesValue) || !Number.isInteger(maxRoutesValue)) {
      setError("候補件数は整数で入力してください。");
      return false;
    }
    if (maxRoutesValue < 1 || maxRoutesValue > MAX_ROUTES) {
      setError(`候補件数は1〜${MAX_ROUTES}件で入力してください。`);
      return false;
    }
    return true;
  }

  function handleSubmit() {
    if (routeMode === "destination") {
      // 経由地・目的地のいずれも未指定のサイレント失敗を防ぐ。
      if (waypointCount === 0 && destinationState !== "set") {
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

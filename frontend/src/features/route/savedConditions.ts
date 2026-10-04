import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import type { RouteMode } from "@/features/route/RouteForm/useRouteFormSubmit";
import { syncHardFilterKeys } from "@/features/route/hardFilterSync";
import type { Coordinates, HardFilterOverride, RoutePreferenceWeights } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

/** 名前を付けて保存する生成の条件。その日の走行条件（出発時刻・想定速度・走行方位）と、生成した候補は持たない。 */
export interface GenerationConditionsSnapshot {
  routeMode: RouteMode;
  /** 距離の入力（文字列のまま。「ルート設定」が持つ形）。 */
  distance: string;
  /** 候補数の入力（同上）。 */
  maxRoutes: string;
  /** 地図で置いた出発地。nullは「現在地から」で、呼び出したときの現在地から生成する。 */
  origin: Coordinates | null;
  waypoints: Coordinates[];
  destination: Coordinates | null;
  /** 上書きした重み。nullは上書きしない（backendの既定の配分）。 */
  routePreference: RoutePreferenceWeights | null;
  hardFilters: HardFilterOverride;
}

export interface SavedCondition extends GenerationConditionsSnapshot {
  name: string;
}

/** 距離の入力として受け付ける値か（画面の範囲内の数値）。範囲が縮んだ後でも、範囲外の距離が復元されて送られない。 */
export function acceptedDistanceInput(raw: string): string | null {
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 1 && parsed <= routeGenerateConfig.max_distance_km ? raw : null;
}

/** 候補数の入力として受け付ける値か。 */
export function acceptedMaxRoutesInput(raw: string): string | null {
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed >= 1 && parsed <= routeGenerateConfig.max_routes ? raw : null;
}

function isCoordinates(value: unknown): value is Coordinates {
  if (typeof value !== "object" || value === null) return false;
  const { latitude, longitude } = value as Record<string, unknown>;
  return (
    typeof latitude === "number" &&
    Number.isFinite(latitude) &&
    typeof longitude === "number" &&
    Number.isFinite(longitude)
  );
}

function isWeights(value: unknown): value is RoutePreferenceWeights {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.values(value).every((weight) => typeof weight === "number" && Number.isFinite(weight))
  );
}

// 1件を今の画面が受け付ける形で読む。読めない件はnull（ほかの件は残す）。重みの軸は読むときに揃えず、呼び出して
// 「重み」へ入れたあと、いつもの保存値と同じく軸カタログの公開軸へ揃える。
function readSavedCondition(value: unknown): SavedCondition | null {
  if (typeof value !== "object" || value === null) return null;
  const entry = value as Record<string, unknown>;
  const { name, routeMode, distance, maxRoutes, origin, waypoints, destination, routePreference, hardFilters } = entry;
  if (typeof name !== "string" || name.trim() === "") return null;
  if (routeMode !== "loop" && routeMode !== "destination") return null;
  if (typeof distance !== "string" || acceptedDistanceInput(distance) === null) return null;
  if (typeof maxRoutes !== "string" || acceptedMaxRoutesInput(maxRoutes) === null) return null;
  if (origin !== null && !isCoordinates(origin)) return null;
  if (
    !Array.isArray(waypoints) ||
    waypoints.length > routeGenerateConfig.max_waypoints ||
    !waypoints.every(isCoordinates)
  ) {
    return null;
  }
  if (destination !== null && !isCoordinates(destination)) return null;
  if (routePreference !== null && !isWeights(routePreference)) return null;
  if (typeof hardFilters !== "object" || hardFilters === null) return null;
  return {
    name,
    routeMode,
    distance,
    maxRoutes,
    origin,
    waypoints,
    destination,
    routePreference,
    hardFilters: syncHardFilterKeys(hardFilters as HardFilterOverride, DEFAULT_HARD_FILTERS),
  };
}

/** 保存した一覧を読む。壊れた保存値は空の一覧、読めない件はその件だけを捨てる。 */
export function readSavedConditions(raw: string): SavedCondition[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  return parsed.map(readSavedCondition).filter((entry): entry is SavedCondition => entry !== null);
}

/** 名前の欄に最初から入れておく仮の名前。 */
export function suggestedConditionName(conditions: GenerationConditionsSnapshot): string {
  if (conditions.routeMode === "loop") return `周回 ${conditions.distance}km`;
  return conditions.waypoints.length > 0 ? `目的地 経由${conditions.waypoints.length}地点` : "目的地";
}

/** 一覧の行に名前と並べる、何が入っているかの短い説明。 */
export function savedConditionSummary(entry: SavedCondition): string {
  const route =
    entry.routeMode === "loop"
      ? `周回 ${entry.distance}km`
      : entry.waypoints.length > 0
        ? `目的地・経由${entry.waypoints.length}地点`
        : "目的地";
  return `${route}・${entry.origin === null ? "現在地から" : "地図で置いた出発地から"}`;
}

/** 保存した一覧へ1件を入れる。同じ名前の件は上書きし、入れた件を先頭に置く（最近保存したものほど上）。 */
export function withSavedCondition(list: SavedCondition[], entry: SavedCondition): SavedCondition[] {
  return [entry, ...list.filter((saved) => saved.name !== entry.name)];
}

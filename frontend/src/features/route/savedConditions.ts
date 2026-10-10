import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import type { RouteMode } from "@/features/route/RouteForm/useRouteFormSubmit";
import { syncHardFilterKeys } from "@/features/route/hardFilterSync";
import { alignRoutePreference } from "@/features/route/routePreferenceSync";
import { totalWeight } from "@/features/route/routeWeightShare";
import type { AxisCatalog } from "@/lib/axisCatalog";
import type { Coordinates, HardFilterOverride, RoutePreferenceWeights } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

/** 生成の条件（「ルート設定」の入力）。いまの条件・保存・呼び出しが同じこの形を使う。出発地は位置の持ち主が持つので含まず、
 * その日の走行条件（出発時刻・想定速度・走行方位）と、生成した候補も持たない。 */
export interface GenerationConditionsSnapshot {
  routeMode: RouteMode;
  /** 距離の入力（文字列のまま。「ルート設定」が持つ形）。 */
  distance: string;
  /** 候補数の入力（同上）。 */
  maxRoutes: string;
  waypoints: Coordinates[];
  destination: Coordinates | null;
  /** 上書きした重み。nullは上書きしない（backendの既定の配分）。 */
  routePreference: RoutePreferenceWeights | null;
  hardFilters: HardFilterOverride;
}

/** 名前を付けて保存した生成の条件。 */
export interface SavedCondition extends GenerationConditionsSnapshot {
  name: string;
  /** 地図で置いた出発地。nullは「現在地から」で、呼び出したときの現在地から生成する。 */
  origin: Coordinates | null;
}

/** 距離の入力の下限（km）。backendは0より大きい距離を受け付け、画面は1km刻みで選ばせるので、その最小の値。 */
export const MIN_DISTANCE_KM = 1;

/** 距離の入力として受け付ける値か（画面の範囲内の数値）。範囲が縮んだ後でも、範囲外の距離が復元されて送られない。 */
export function acceptedDistanceInput(raw: string): string | null {
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= MIN_DISTANCE_KM && parsed <= routeGenerateConfig.max_distance_km
    ? raw
    : null;
}

/** 候補数の入力として受け付ける値か。 */
export function acceptedMaxRoutesInput(raw: string): string | null {
  const parsed = Number(raw);
  return Number.isInteger(parsed) &&
    parsed >= routeGenerateConfig.min_routes &&
    parsed <= routeGenerateConfig.max_routes
    ? raw
    : null;
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
    Object.values(value).every((weight) => typeof weight === "number" && Number.isFinite(weight) && weight >= 0)
  );
}

const coordinatesOrNull = (value: unknown) => (value === null || isCoordinates(value) ? value : undefined);

// 保存した1件の項目ごとの読み方。今の画面が受け付けない値はundefinedを返し、その件を捨てる。キーは保存の形と同じ型の
// 写像なので、形に項目を足すと読み方が要る（前に保存した件はその項目を持たないので、読み方が扱いを決める）。重みの軸は
// 読むときに揃えず、呼び出して「重み」へ入れたあと、いつもの保存値と同じく軸カタログの公開軸へ揃える。
const SAVED_FIELD_READERS: { [K in keyof SavedCondition]-?: (value: unknown) => SavedCondition[K] | undefined } = {
  name: (value) => (typeof value === "string" && value.trim() !== "" ? value : undefined),
  routeMode: (value) => (value === "loop" || value === "destination" ? value : undefined),
  distance: (value) => (typeof value === "string" ? (acceptedDistanceInput(value) ?? undefined) : undefined),
  maxRoutes: (value) => (typeof value === "string" ? (acceptedMaxRoutesInput(value) ?? undefined) : undefined),
  origin: coordinatesOrNull,
  waypoints: (value) =>
    Array.isArray(value) && value.length <= routeGenerateConfig.max_waypoints && value.every(isCoordinates)
      ? value
      : undefined,
  destination: coordinatesOrNull,
  routePreference: (value) => (value === null || isWeights(value) ? value : undefined),
  hardFilters: (value) =>
    typeof value === "object" && value !== null
      ? syncHardFilterKeys(value as HardFilterOverride, DEFAULT_HARD_FILTERS)
      : undefined,
};

// 1件を今の画面が受け付ける形で読む。読めない件はnull（ほかの件は残す）。
function readSavedCondition(value: unknown): SavedCondition | null {
  if (typeof value !== "object" || value === null) return null;
  const entry = value as Record<string, unknown>;
  const read: Record<string, unknown> = {};
  for (const [key, readField] of Object.entries(SAVED_FIELD_READERS)) {
    const field = readField(entry[key]);
    if (field === undefined) return null;
    read[key] = field;
  }
  return read as unknown as SavedCondition;
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

/** 保存の前と一覧の行に並べる、何が保存されるかの説明（出発地は`originDescription`）。 */
interface ConditionsDescription {
  /** 周回か目的地か・距離・経由地・候補数。 */
  route: string;
  /** 使う軸ごとの割合（重みの合計に占める%。「重み」タブのチップと同じ数）。 */
  weights: string;
  /** 除外する道路の名前。 */
  exclusions: string;
}

function routeDescription(conditions: GenerationConditionsSnapshot): string {
  const route =
    conditions.routeMode === "loop"
      ? `周回 ${conditions.distance}km`
      : conditions.waypoints.length > 0
        ? `目的地へ・経由 ${conditions.waypoints.length}地点`
        : "目的地へ";
  return `${route}・候補 ${conditions.maxRoutes}本`;
}

// 上書きしない重みは、生成のときbackendの既定の配分で探すので、軸カタログが配る既定の重みを割合にして見せる。
// 上書きした重みは、呼び出して送るときと同じく公開軸へ揃えてから割合にする。上書きしたかは出さない（残るのは割合だけ）。
function weightsDescription(routePreference: RoutePreferenceWeights | null, catalog: AxisCatalog): string {
  const weights = alignRoutePreference(routePreference ?? catalog.defaultWeights, catalog);
  const total = totalWeight(weights);
  const shares = catalog.axes
    .filter((axis) => weights[axis.axisId] > 0)
    .map((axis) => ({ label: axis.label, pct: Math.round((weights[axis.axisId] / total) * 100) }))
    .sort((a, b) => b.pct - a.pct);
  return shares.length === 0 ? "—" : shares.map(({ label, pct }) => `${label} ${pct}%`).join("・");
}

function exclusionsDescription(hardFilters: HardFilterOverride): string {
  const labels = routeGenerateConfig.hard_filters.filters
    .filter(({ key }) => hardFilters[key])
    .map(({ label }) => label);
  return labels.length === 0 ? "なし" : labels.join("・");
}

export function describeConditions(
  conditions: GenerationConditionsSnapshot,
  catalog: AxisCatalog,
): ConditionsDescription {
  return {
    route: routeDescription(conditions),
    weights: weightsDescription(conditions.routePreference, catalog),
    exclusions: exclusionsDescription(conditions.hardFilters),
  };
}

/** 出発地の扱いの名前（`fixed`は保存した地点から作る）。 */
export function originDescription(fixed: boolean): string {
  return fixed ? "保存した地点に固定" : "呼び出した時の現在地";
}

/** 保存した一覧へ1件を入れる。同じ名前の件は上書きし、入れた件を先頭に置く（最近保存したものほど上）。 */
export function withSavedCondition(list: SavedCondition[], entry: SavedCondition): SavedCondition[] {
  return [entry, ...list.filter((saved) => saved.name !== entry.name)];
}

import type {
  Coordinates,
  HardFilterOverride,
  RouteGenerateRequest,
  RoutePreferenceWeights,
} from "@/types/route";

// 生成リクエストのpayloadと、「条件が変更されています」（conditionsDirty）の比較キーを
// **同じ入力から**組み立てる。
//
// payloadと比較対象を別々に並べると、送る値を足したときに比較側へ足し忘れても何も壊れず、
// 「変えたのにバッジが出ない」形でしか現れない。送る値をここで1度だけ決め、比較キーは
// そこから導出することで「送るのに比較しないフィールド」を作れなくする。

/** 生成リクエストを決める入力一式（画面の状態から実効値へ解決済み）。 */
export interface GenerationInput {
  origin: Coordinates;
  /** 実効距離（目的地モードは指定点の最遠距離から自動算出した値）。 */
  distanceKm: number;
  distanceToleranceKm: number;
  maxRoutes: number;
  assumedSpeedKmh: number;
  startTime: Date;
  penaltyStrength: number;
  hardFilters: HardFilterOverride;
  /** レンズが軸を指している場合のみ。地図の見え方の選択で、候補の選定には影響しない。 */
  lensAxisId: string | null;
  /** 重み上書きが有効なときのみ（無効ならbackendの既定値に委ねる）。 */
  routePreference: RoutePreferenceWeights | null;
  /** 目的地モードのときだけ値を持つ（周回モードでは常に空・null）。 */
  waypoints: readonly Coordinates[];
  destination: Coordinates | null;
  /** 経由地を伴う目的地ルートではbackendがmax_routesを無視する（常に1件へ固定する）。 */
  maxRoutesRelevant: boolean;
}

/** 画面の状態からbackendへ送るpayloadを組み立てる。 */
export function buildGenerateRequest(input: GenerationInput): RouteGenerateRequest {
  return {
    latitude: input.origin.latitude,
    longitude: input.origin.longitude,
    distance_km: input.distanceKm,
    distance_tolerance_km: input.distanceToleranceKm,
    route_type: "loop",
    penalty_strength: input.penaltyStrength,
    // hard_filtersは一般向けルート設定画面（RouteSettingsPanel）が常時操作する対象の
    // ため、重み上書きのようなトグルを介さず常に送る（既定値はbackendの
    // DEFAULT_HARD_FILTERSと一致するため挙動は変わらない）。
    hard_filters: input.hardFilters,
    // RouteGenerateRequest.max_routesは既定値を持つがrequiredのため、モードに関わらず
    // 常に送る（経由地を伴う目的地ルートではbackendが値を無視する）。
    max_routes: input.maxRoutes,
    assumed_speed_kmh: input.assumedSpeedKmh,
    start_time: input.startTime.toISOString(),
    // レンズが軸を要求していれば、重み0でも区間表示のため風の時変化合成を行う（backend）。
    ...(input.lensAxisId !== null ? { lens_axis_id: input.lensAxisId } : {}),
    ...(input.routePreference !== null ? { route_preference: input.routePreference } : {}),
    // 目的地モードのときだけ経由地・目的地を送る（backend側の分岐はapi/routers/routes.py）。
    ...(input.waypoints.length > 0 ? { waypoints: [...input.waypoints] } : {}),
    ...(input.destination !== null ? { destination: input.destination } : {}),
  };
}

/** 比較対象から外すpayloadフィールドと、その理由。
 *
 * ここに挙げた以外は**すべて**比較対象になる。payloadへフィールドを足したときに
 * 比較側へ足し忘れることが起きないよう、除外は明示的な列挙だけに限る。 */
const IGNORED_WHEN_COMPARING = {
  // レンズは地図の見え方の選択で、候補の選定（探索コスト）には影響しない。頻繁に
  // 切り替えるため、変えるたびに「条件が変更されています」を出すと通知が意味を失う。
  lens_axis_id: "地図の見え方の選択で、候補の選定には影響しない",
} as const;

/** キー順に依存しないJSON化。`hard_filters`・`route_preference`のように、同じ内容でも
 * 組み立て方（保存値からの復元・キー整合による補完）でプロパティの並びが変わりうる
 * オブジェクトを、並びの違いだけで「条件が変わった」と誤判定しないため。配列
 * （`waypoints`）は順序自体に意味があるのでそのまま保つ。 */
function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/**
 * `conditionsDirty`の比較キー。payloadと同じ入力から作るため、送る値の変更は
 * `IGNORED_WHEN_COMPARING`に挙げたもの以外すべてが差分として現れる。
 *
 * `maxRoutesRelevant=false`（経由地を伴う目的地ルート）のときは`max_routes`も外す
 * ——backendが値を無視するため、変えても表示中の候補と実際に食い違わない。
 */
export function generationConditionsKey(input: GenerationInput): string {
  const request = buildGenerateRequest(input) as Record<string, unknown>;
  const comparable: Record<string, unknown> = {};
  for (const key of Object.keys(request)) {
    if (key in IGNORED_WHEN_COMPARING) continue;
    if (key === "max_routes" && !input.maxRoutesRelevant) continue;
    comparable[key] = request[key];
  }
  return stableStringify(comparable);
}

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

// 候補タブの表記を組み立てる純関数。
//
// タブは候補どうしを見比べる場所のため、「基準線からどれだけ余計にかかるか」はここに出す
// （タブの中身を開かないと分からないと、比較のたびに開き直すことになる）。

/** 区間を乗り換えて作った候補のid接頭辞。**backendが付ける値**（route_generator.py:
 * generate_spliced_route）で、同じ生成結果へ複数追加できるようフロントが連番を足す。
 * 判定と組み立ての両方がこの1つを使う——別々に書くと、片方だけ変えたときに合成した
 * ルートが一覧の中で生成候補と見分けられなくなる（型でも例外でも現れない）。 */
// backendが付けるidそのもの（生成物経由で受け取る）。両側で別々に書くと、片方だけ改名
// したときに合成ルートが一覧で生成候補と見分けられなくなる。
export const SPLICED_ROUTE_ID_PREFIX = routeGenerateConfig.spliced_route_id;

/** 区間を乗り換えて作った候補か。一覧では生成候補と並ぶため、由来を表記で示す。
 * 並び順（overall_difficulty昇順）の外へ追加されるので、順位番号は意味を持たない。 */
export function isSplicedRoute(route: { id: string }): boolean {
  return route.id.startsWith(SPLICED_ROUTE_ID_PREFIX);
}

/** 基準線となる候補（RouteCandidate.is_fastest＝好みの重みを0にしたときの経路）の
 * 所要時間（秒）。基準線が無い・所要時間を持たないときはnull。 */
export function fastestDurationSeconds(
  routes: readonly { estimated_duration_seconds?: number | null; is_fastest?: boolean }[],
): number | null {
  const fastest = routes.find((route) => route.is_fastest);
  return fastest?.estimated_duration_seconds ?? null;
}

/**
 * 基準線より何分余計にかかるかの表記（例: `+12分`）。基準線が無い・自分が基準線・
 * 自分の所要時間が無い・差が丸めて1分未満のときはnull（0を並べても判断材料にならない）。
 */
export function extraDurationLabel(
  route: { estimated_duration_seconds?: number | null; is_fastest?: boolean },
  fastestSeconds: number | null,
): string | null {
  if (fastestSeconds === null || route.is_fastest) return null;
  const seconds = route.estimated_duration_seconds;
  if (seconds === null || seconds === undefined) return null;
  const extraMinutes = Math.round((seconds - fastestSeconds) / 60);
  if (extraMinutes < 1) return null;
  return `+${extraMinutes}分`;
}

/**
 * 一覧の中で最も距離が短い候補のid。候補が1件以下ならnull（比べる相手が無い）。
 *
 * 目的地モードの`is_fastest`（backendが基準線として付ける）とは別に、周回モードを
 * 含むどの一覧でも「最短はどれか」を一覧の中だけで決められるようにする——一覧を見ただけで
 * 分かることが目的で、並び順（総合難易度の昇順）とは別の軸だから印が要る。
 */
export function shortestDistanceRouteId(routes: readonly { id: string; distance_km: number }[]): string | null {
  if (routes.length < 2) return null;
  return routes.reduce((best, route) => (route.distance_km < best.distance_km ? route : best)).id;
}

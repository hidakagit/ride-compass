// 候補タブの表記を組み立てる純関数。
//
// タブは候補どうしを見比べる場所のため、「最短からどれだけ余分に走るか」はここに出す
// （タブの中身を開かないと分からないと、比較のたびに開き直すことになる）。

/** 区間を乗り換えて作った候補のid接頭辞。**backendが付ける値**（route_generator.py:
 * generate_spliced_route）で、同じ生成結果へ複数追加できるようフロントが連番を足す。
 * 判定と組み立ての両方がこの1つを使う——別々に書くと、片方だけ変えたときに合成した
 * ルートが一覧の中で生成候補と見分けられなくなる（型でも例外でも現れない）。 */
export const SPLICED_ROUTE_ID_PREFIX = "route-spliced";

/** 区間を乗り換えて作った候補か。一覧では生成候補と並ぶため、由来を表記で示す。
 * 並び順（overall_difficulty昇順）の外へ追加されるので、順位番号は意味を持たない。 */
export function isSplicedRoute(route: { id: string }): boolean {
  return route.id.startsWith(SPLICED_ROUTE_ID_PREFIX);
}

/** 距離だけで選んだ基準線となる候補（RouteCandidate.is_shortest_distance）の距離km。無ければnull。 */
export function shortestDistanceKm(
  routes: readonly { distance_km: number; is_shortest_distance?: boolean }[],
): number | null {
  const shortest = routes.find((route) => route.is_shortest_distance);
  return shortest ? shortest.distance_km : null;
}

/**
 * 最短経路より何km余分に走るかの表記（例: `+4.0`）。基準線が無い・自分が基準線・
 * 差が丸めて0.1km未満のときはnull（0を並べても判断材料にならない）。
 */
export function extraDistanceLabel(
  route: { distance_km: number; is_shortest_distance?: boolean },
  shortestKm: number | null,
): string | null {
  if (shortestKm === null || route.is_shortest_distance) return null;
  const extra = route.distance_km - shortestKm;
  if (extra < 0.05) return null;
  return `+${extra.toFixed(1)}`;
}

/**
 * 一覧の中で最も距離が短い候補のid。候補が1件以下ならnull（比べる相手が無い）。
 *
 * 目的地モードの`is_shortest_distance`（backendが基準線として付ける）とは別に、周回モードを
 * 含むどの一覧でも「最短はどれか」を一覧の中だけで決められるようにする——一覧を見ただけで
 * 分かることが目的で、並び順（総合難易度の昇順）とは別の軸だから印が要る。
 */
export function shortestDistanceRouteId(routes: readonly { id: string; distance_km: number }[]): string | null {
  if (routes.length < 2) return null;
  return routes.reduce((best, route) => (route.distance_km < best.distance_km ? route : best)).id;
}

// 候補タブの表記を組み立てる純関数。
//
// タブは候補どうしを見比べる場所のため、「最短からどれだけ余分に走るか」はここに出す
// （タブの中身を開かないと分からないと、比較のたびに開き直すことになる）。

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

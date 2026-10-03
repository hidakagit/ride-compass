// 難易度の帯へ距離の次元を与え、負荷（総合難易度×距離）を面積で表すための高さ比。
//
// 帯は長さが総合難易度を表している（幅いっぱい＝100の目盛り）。ここへ高さとして距離を
// 与えると、塗られた面積がそのまま負荷になり、積み上げの色ごとの面積が軸別の負荷になる。

/** 高さの倍率の上限。距離の比をそのまま高さにすると、短い候補と長い候補が混ざる目的地
 * モードで行の高さが破綻する。頭打ちにしたぶん面積は負荷に厳密比例しなくなるため、
 * 負荷の数値は帯と併せて出す。 */
export const LOAD_BAR_MAX_HEIGHT_RATIO = 2;

/** 高さ1.0とする距離（一覧の中で最も短い候補の距離）。距離を持つ候補が無ければnull。
 *
 * **一覧の中だけで決める**（`routeTabLabel.ts: fastestRouteId`と同じ考え方）。基準を
 * backendの値や目標距離から取ると、周回モードのように目標を持つ生成と、目的地モードの
 * ように持たない生成とで基準の意味が変わり、同じ高さが別のことを指すようになる。 */
export function baselineDistanceKm(routes: readonly { distance_km?: number | null }[]): number | null {
  let min: number | null = null;
  for (const route of routes) {
    const km = route.distance_km;
    if (km === null || km === undefined || !Number.isFinite(km) || km <= 0) continue;
    if (min === null || km < min) min = km;
  }
  return min;
}

/** 帯の高さの倍率（基準距離に対する比を1.0〜`LOAD_BAR_MAX_HEIGHT_RATIO`へ収めた値）。
 * 基準が無い・自分の距離が無いときは1.0で、そのとき帯は長さだけを表す従来の見た目になる。 */
export function loadBarHeightRatio(distanceKm: number | null | undefined, baselineKm: number | null): number {
  if (baselineKm === null || baselineKm <= 0) return 1;
  if (distanceKm === null || distanceKm === undefined || !Number.isFinite(distanceKm)) return 1;
  const ratio = distanceKm / baselineKm;
  if (!(ratio > 1)) return 1;
  // DOMへ書く値のため丸める（生の比は候補ごとに末尾まで違い、差が見た目に出ない桁まで
  // スタイルが変わる）。
  return Math.round(Math.min(ratio, LOAD_BAR_MAX_HEIGHT_RATIO) * 100) / 100;
}

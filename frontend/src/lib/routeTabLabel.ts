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

/**
 * 一覧の中で最も所要時間が短い候補のid（＝基準線）。候補が1件以下、または所要時間を持つ
 * 候補が無ければnull（比べる相手が無い）。
 *
 * **backendの`is_fastest`は見ない**——あれは目的地モードでしか付かず、周回モードでは
 * 基準線が一度も決まらない。主用途である周回でも「何と比べた+N分か」を出せるよう、
 * 一覧の中だけで決める。同着は先に来た方（並び順は総合難易度の昇順なので、易しい方）。
 */
export function fastestRouteId(
  routes: readonly { id: string; estimated_duration_seconds?: number | null }[],
): string | null {
  if (routes.length < 2) return null;
  let best: { id: string; seconds: number } | null = null;
  for (const route of routes) {
    const seconds = route.estimated_duration_seconds;
    if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) continue;
    if (best === null || seconds < best.seconds) best = { id: route.id, seconds };
  }
  return best?.id ?? null;
}

/** 基準線（`fastestRouteId`が返す候補）の所要時間（秒）。基準線が無ければnull。 */
export function fastestDurationSeconds(
  routes: readonly { id: string; estimated_duration_seconds?: number | null }[],
): number | null {
  const id = fastestRouteId(routes);
  if (id === null) return null;
  return routes.find((route) => route.id === id)?.estimated_duration_seconds ?? null;
}

/**
 * 基準線より何分余計にかかるかの表記（例: `+12分`）。基準線が無い・自分の所要時間が
 * 無い・差が丸めて1分未満のときはnull（0を並べても判断材料にならない。自分が基準線の
 * ときも差0なのでここに入る）。
 */
export function extraDurationLabel(
  route: { estimated_duration_seconds?: number | null },
  fastestSeconds: number | null,
): string | null {
  if (fastestSeconds === null) return null;
  const seconds = route.estimated_duration_seconds;
  if (seconds === null || seconds === undefined) return null;
  const extraMinutes = Math.round((seconds - fastestSeconds) / 60);
  if (extraMinutes < 1) return null;
  return `+${extraMinutes}分`;
}

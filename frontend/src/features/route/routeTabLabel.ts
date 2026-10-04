import routeGenerateConfig from "@/types/generated/route-generate-config.json";

// 候補タブの表記を組み立てる純関数。
//
// タブは候補どうしを見比べる場所のため、「基準線からどれだけ余計にかかるか」はここに出す
// （タブの中身を開かないと分からないと、比較のたびに開き直すことになる）。

/** 区間を乗り換えて作ったルートのid接頭辞。**backendが付ける値**（route_generator.py:
 * generate_spliced_route）で、同じ生成結果へ複数追加できるようフロントが作った順の番号を足す。 */
export const SPLICED_ROUTE_ID_PREFIX = routeGenerateConfig.spliced_route_id;

// 経由地ルートのid（常に1件、「方位」という概念が無いため順位番号の代わりに名前を出す）。
const NON_DIRECTIONAL_ROUTE_IDS = new Set([routeGenerateConfig.waypoints_route_id]);

/** 一覧の群。並びは最速 → 生成した候補 → 合成で、群が変わる所に区切りの線を引く。 */
export type RouteListGroup = "fastest" | "generated" | "spliced";

/**
 * 一覧の1行。`name`はそのルートを指す名前（「元との違い」の元の名前にも使う）で、`label`は名前の列に印と並べて
 * 出す文字（最速は印だけなので空、合成は番号）。
 */
interface RouteListEntry<T> {
  route: T;
  group: RouteListGroup;
  name: string;
  label: string;
}

/** 一覧の先頭に置く、所要時間だけで選んだ候補の名前。 */
const FASTEST_ROUTE_NAME = "最速";

/**
 * 「ルート結果」の一覧の並びと名前。
 *
 * `pinsFastest`（生成が所要時間だけで選んだ1本を必ず含める目的地ルート）なら、最も早く着く生成候補を「最速」として
 * 先頭に置き、残りの生成候補に1から番号を振り、合成で作ったルートを作った順に「合成N」で続ける。比べる基準の1本を、
 * 合成の前後で動かさずに一番上へ置くため。
 */
export function routeListEntries<
  T extends { id: string; direction_label: string; estimated_duration_seconds: number | null },
>(generated: readonly T[], edits: readonly { route: T; number: number }[], pinsFastest: boolean): RouteListEntry<T>[] {
  const pinnedId = pinsFastest ? fastestRouteId(generated) : null;
  const fastest = generated
    .filter((route) => route.id === pinnedId)
    .map((route) => ({ route, group: "fastest" as const, name: FASTEST_ROUTE_NAME, label: "" }));
  const numbered = generated
    .filter((route) => route.id !== pinnedId)
    .map((route, index) => {
      const name = NON_DIRECTIONAL_ROUTE_IDS.has(route.id) ? route.direction_label : `${index + 1}`;
      return { route, group: "generated" as const, name, label: name };
    });
  const spliced = edits.map(({ route, number }) => ({
    route,
    group: "spliced" as const,
    name: `合成${number}`,
    label: `${number}`,
  }));
  return [...fastest, ...numbered, ...spliced];
}

type TimedRoute = { id: string; estimated_duration_seconds: number | null };

/**
 * 一覧の中で最も所要時間が短い候補（＝基準線）。候補が1件以下、または所要時間を持つ
 * 候補が無ければnull（比べる相手が無い）。
 *
 * 一覧の中だけで決める——周回・目的地のどちらでも、区間を乗り換えて作った候補を含めて
 * 「何と比べた+N分か」を同じ判定で出すため。同着は先に来た方（並び順は総合難易度の昇順なので、易しい方）。
 */
function fastestRoute(routes: readonly TimedRoute[]): { id: string; seconds: number } | null {
  if (routes.length < 2) return null;
  let best: { id: string; seconds: number } | null = null;
  for (const route of routes) {
    const seconds = route.estimated_duration_seconds;
    if (seconds === null) continue;
    if (best === null || seconds < best.seconds) best = { id: route.id, seconds };
  }
  return best;
}

/** 基準線のid。基準線が無ければnull。 */
export function fastestRouteId(routes: readonly TimedRoute[]): string | null {
  return fastestRoute(routes)?.id ?? null;
}

/** 基準線の所要時間（秒）。基準線が無ければnull。 */
export function fastestDurationSeconds(routes: readonly TimedRoute[]): number | null {
  return fastestRoute(routes)?.seconds ?? null;
}

/**
 * 基準線より何分余計にかかるかの表記（例: `+12分`・`+107分`）。基準線が無い・自分の所要時間が
 * 無い・差が丸めて1分未満のときはnull（0を並べても判断材料にならない。自分が基準線の
 * ときも差0なのでここに入る）。
 */
export function extraDurationLabel(
  route: { estimated_duration_seconds: number | null },
  fastestSeconds: number | null,
): string | null {
  if (fastestSeconds === null) return null;
  const seconds = route.estimated_duration_seconds;
  if (seconds === null) return null;
  const extraMinutes = Math.round((seconds - fastestSeconds) / 60);
  if (extraMinutes < 1) return null;
  return `+${extraMinutes}分`;
}

/**
 * 生成した候補の並び: 所要時間の短い順。所要時間の無い候補は末尾。同じ所要時間は受け取った並び（backendの総合難易度の
 * 昇順）を保つので、同着なら易しい方が先。
 */
export function orderByDuration<T extends { estimated_duration_seconds: number | null }>(routes: readonly T[]): T[] {
  const secondsOf = (route: T) => route.estimated_duration_seconds ?? Number.POSITIVE_INFINITY;
  return routes
    .map((route, index) => ({ route, index }))
    .sort((a, b) => secondsOf(a.route) - secondsOf(b.route) || a.index - b.index)
    .map(({ route }) => route);
}

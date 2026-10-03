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

/** 一覧の1行。`name`は元との違い等でそのルートを指す名前で、`nameShown`がfalseなら行には出さない。 */
interface RouteListEntry<T> {
  route: T;
  name: string;
  nameShown: boolean;
}

/** 一覧の見出し1つ分。見出しを持たない一覧（周回等）は`title`がnullの1つだけになる。 */
interface RouteListSection<T> {
  title: string | null;
  entries: RouteListEntry<T>[];
}

/** 見出しを分けたときに採用ルートの先頭へ置く、所要時間だけで選んだ候補の名前。 */
export const FASTEST_ROUTE_NAME = "最速";

/**
 * 「ルート結果」の一覧の並びと名前。
 *
 * `pinsFastest`（生成が所要時間だけで選んだ1本を必ず含める目的地ルート）なら、最も早く着く生成候補を「採用ルート」の
 * 先頭に置き、編集で作ったルートを作った順に続ける。残りの生成候補は「生成した候補」として1から番号を振る。
 * 比べる基準の1本を、編集の前後で動かさずに一番上へ置くため。見出しを分けないときは生成候補に1から番号を振る。
 */
export function routeListSections<
  T extends { id: string; direction_label: string; estimated_duration_seconds?: number | null },
>(
  generated: readonly T[],
  edits: readonly { route: T; number: number }[],
  pinsFastest: boolean,
): RouteListSection<T>[] {
  const pinnedId = pinsFastest ? fastestRouteId(generated) : null;
  const numbered = (routes: readonly T[]): RouteListEntry<T>[] =>
    routes.map((route, index) =>
      NON_DIRECTIONAL_ROUTE_IDS.has(route.id)
        ? { route, name: route.direction_label, nameShown: true }
        : { route, name: `${index + 1}`, nameShown: true },
    );
  const edited = edits.map(({ route, number }) => ({ route, name: `編集${number}`, nameShown: true }));
  if (pinnedId === null && edited.length === 0) return [{ title: null, entries: numbered(generated) }];
  const pinned = generated.filter((route) => route.id === pinnedId);
  return [
    {
      title: "採用ルート",
      entries: [...pinned.map((route) => ({ route, name: FASTEST_ROUTE_NAME, nameShown: false })), ...edited],
    },
    { title: "生成した候補", entries: numbered(generated.filter((route) => route.id !== pinnedId)) },
  ];
}

/**
 * 一覧の中で最も所要時間が短い候補のid（＝基準線）。候補が1件以下、または所要時間を持つ
 * 候補が無ければnull（比べる相手が無い）。
 *
 * 一覧の中だけで決める——周回・目的地のどちらでも、区間を乗り換えて作った候補を含めて
 * 「何と比べた+N分か」を同じ判定で出すため。同着は先に来た方（並び順は総合難易度の昇順なので、易しい方）。
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
 * 基準線より何分余計にかかるかの表記（例: `+12分`・`+107分`）。基準線が無い・自分の所要時間が
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

/**
 * 生成した候補の並び: 所要時間の短い順。所要時間の無い候補は末尾。同じ所要時間は受け取った並び（backendの総合難易度の
 * 昇順）を保つので、同着なら易しい方が先。
 */
export function orderByDuration<T extends { estimated_duration_seconds?: number | null }>(routes: readonly T[]): T[] {
  const secondsOf = (route: T) => {
    const seconds = route.estimated_duration_seconds;
    return seconds === null || seconds === undefined || !Number.isFinite(seconds) ? Number.POSITIVE_INFINITY : seconds;
  };
  return routes
    .map((route, index) => ({ route, index }))
    .sort((a, b) => secondsOf(a.route) - secondsOf(b.route) || a.index - b.index)
    .map(({ route }) => route);
}

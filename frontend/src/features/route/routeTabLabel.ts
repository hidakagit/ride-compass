import type { RouteCandidate } from "@/types/route";

// 候補タブの表記を組み立てる純関数。
//
// タブは候補どうしを見比べる場所のため、「基準線とどれだけ違うか」はここに出す
// （タブの中身を開かないと分からないと、比較のたびに開き直すことになる）。
//
// 候補の種類と最速の印は**backendが付ける値**（route_generator.py: _label）で、ここは読むだけ。idの文字列や
// 生成の要求の形から種類を決め直さない。

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

/** 一覧の先頭に置く、所要時間だけで探した候補の名前。 */
const FASTEST_ROUTE_NAME = "最速";

type ListedRoute = Pick<RouteCandidate, "id" | "kind" | "direction_label" | "is_fastest">;

/**
 * 「ルート結果」の一覧の並びと名前。
 *
 * 最速の印の付いた1本を「最速」として先頭に置き、残りの生成候補に1から番号を振り、合成で作ったルートを作った順に
 * 「合成N」で続ける。比べる基準の1本を、合成の前後で動かさずに一番上へ置くため。経由地を通る1本は常に1本で
 * 順位を持たないので、番号の代わりにbackendが付けた名前を出す。
 */
export function routeListEntries<T extends ListedRoute>(
  generated: readonly T[],
  edits: readonly { route: T; number: number }[],
): RouteListEntry<T>[] {
  const fastest = generated
    .filter((route) => route.is_fastest)
    .map((route) => ({ route, group: "fastest" as const, name: FASTEST_ROUTE_NAME, label: "" }));
  const numbered = generated
    .filter((route) => !route.is_fastest)
    .map((route, index) => {
      const name = route.kind === "waypoints" ? route.direction_label : `${index + 1}`;
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

type TimedRoute = Pick<RouteCandidate, "id" | "estimated_duration_seconds" | "is_fastest">;

/**
 * 時間の列の基準線（そのidと所要時間）。最速の印の付いた1本があればそれ（一覧の「最速」と同じ1本と比べる）、
 * 無ければ一覧の中で最も所要時間が短い候補（同着は先に来た方）。候補が1件以下・基準線の所要時間が無いならnull
 * （比べる相手が無い）。
 */
export function durationBaseline(routes: readonly TimedRoute[]): { id: string; seconds: number } | null {
  if (routes.length < 2) return null;
  const marked = routes.find((route) => route.is_fastest);
  if (marked) {
    const seconds = marked.estimated_duration_seconds;
    return seconds === null ? null : { id: marked.id, seconds };
  }
  let best: { id: string; seconds: number } | null = null;
  for (const route of routes) {
    const seconds = route.estimated_duration_seconds;
    if (seconds === null) continue;
    if (best === null || seconds < best.seconds) best = { id: route.id, seconds };
  }
  return best;
}

/**
 * 基準線との差の表記（例: `+12分`・`+107分`・`−3分`。基準線より速く見積もられた候補は−）。基準線が無い・自分の
 * 所要時間が無い・差が丸めて1分未満のときはnull（0を並べても判断材料にならない。自分が基準線のときも差0なので
 * ここに入る）。
 */
export function durationDifferenceLabel(
  route: { estimated_duration_seconds: number | null },
  baselineSeconds: number | null,
): string | null {
  if (baselineSeconds === null) return null;
  const seconds = route.estimated_duration_seconds;
  if (seconds === null) return null;
  const minutes = Math.round((seconds - baselineSeconds) / 60);
  if (minutes === 0) return null;
  return `${minutes > 0 ? "+" : "−"}${Math.abs(minutes)}分`;
}

/**
 * 生成した候補の並び: 最速の印の付いた1本を先頭に、残りを所要時間の短い順。所要時間の無い候補は末尾。同じ所要時間は
 * 受け取った並び（backendの総合難易度の昇順）を保つので、同着なら易しい方が先。
 */
export function orderGenerated<T extends Pick<RouteCandidate, "estimated_duration_seconds" | "is_fastest">>(
  routes: readonly T[],
): T[] {
  const secondsOf = (route: T) => route.estimated_duration_seconds ?? Number.POSITIVE_INFINITY;
  return routes
    .map((route, index) => ({ route, index }))
    .sort(
      (a, b) =>
        Number(b.route.is_fastest) - Number(a.route.is_fastest) ||
        secondsOf(a.route) - secondsOf(b.route) ||
        a.index - b.index,
    )
    .map(({ route }) => route);
}

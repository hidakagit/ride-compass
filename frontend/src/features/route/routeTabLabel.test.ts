// @vitest-environment node
/**
 * `features/route/routeTabLabel.ts`——「ルート結果」の一覧の並び・群・名前と、基準線との差の表記。
 * - `routeListEntries`: 最速の印の1本・残りの生成候補（1からの番号。経由地を通る1本は名前）・合成で作ったルート
 *   （「合成N」）の順に、群を付けて置く
 * - `durationBaseline`: 最速の印の1本があればそれ、無ければ2件以上のうち所要時間が最も短い候補（同着は先の方）
 * - `durationDifferenceLabel`: 基準線との差を丸めて1分以上なら「+N分」・「−N分」で書く
 * - `orderGenerated`: 最速の印の1本を先頭に、残りを所要時間の短い順。所要時間の無い候補は末尾、同着は受け取った並び
 *
 * ここで見ないもの:
 * - 一覧・タブへの描き方（群の印・区切りの線） → `RouteOutcome/RouteOutcome.test.tsx`
 * - 生成した候補をこの並びで結果へ渡すこと → `useRouteGeneration.test.ts`
 */
import { describe, expect, it } from "vitest";

import { makeRouteCandidate } from "@/testing/routeFixtures";
import type { RouteCandidate } from "@/types/route";

import { durationBaseline, durationDifferenceLabel, orderGenerated, routeListEntries } from "./routeTabLabel";

function route(id: string, seconds: number | null, overrides: Partial<RouteCandidate> = {}) {
  return makeRouteCandidate({ id, direction_label: `${id}の方位`, estimated_duration_seconds: seconds, ...overrides });
}

/** 行を「id:群:名前/名前の列の文字」で並べる。 */
function entriesOf(entries: ReturnType<typeof routeListEntries<RouteCandidate>>) {
  return entries.map((e) => `${e.route.id}:${e.group}:${e.name}/${e.label}`);
}

describe("routeListEntries", () => {
  it("最速の印が無く合成も無ければ、全部を生成した候補として受け取った順で1から番号を振る", () => {
    const generated = [route("a", 900), route("b", 600), route("c", 1200)];
    expect(entriesOf(routeListEntries(generated, []))).toEqual([
      "a:generated:1/1",
      "b:generated:2/2",
      "c:generated:3/3",
    ]);
  });

  it("最速の印の1本を印だけの最速として先頭に置いて残りに1から番号を振り、合成は後へ「合成N」で並べる", () => {
    // 印の1本より速く見積もられた候補があっても、最速は印で決まる
    const generated = [route("a", 900), route("b", 600, { is_fastest: true }), route("c", 500)];
    const edits = [
      { route: route("e2", 700), number: 2 },
      { route: route("e1", 650), number: 1 },
    ];
    expect(entriesOf(routeListEntries(generated, edits))).toEqual([
      "b:fastest:最速/",
      "a:generated:1/1",
      "c:generated:2/2",
      "e2:spliced:合成2/2",
      "e1:spliced:合成1/1",
    ]);
  });

  it("経由地を通る1本は番号の代わりにbackendが付けた名前を出す", () => {
    const waypoints = route("w", 900, { kind: "waypoints", direction_label: "目的地ルート" });
    expect(entriesOf(routeListEntries([waypoints], []))).toEqual(["w:generated:目的地ルート/目的地ルート"]);
  });
});

describe("durationBaseline", () => {
  it("最速の印の1本があれば、ほかに速い候補があってもそれ", () => {
    const routes = [route("a", 500), route("b", 600, { is_fastest: true })];
    expect(durationBaseline(routes)).toEqual({ id: "b", seconds: 600 });
  });

  it("印が無ければ所要時間が最も短い候補で、同着なら先に来た方。所要時間の無い候補は比べない", () => {
    const routes = [route("a", null), route("b", 900), route("c", 600), route("d", 600)];
    expect(durationBaseline(routes)).toEqual({ id: "c", seconds: 600 });
  });

  it.each([
    ["候補が1件", [route("a", 600, { is_fastest: true })]],
    ["所要時間を持つ候補が無い", [route("a", null), route("b", null)]],
    ["印の1本が所要時間を持たない", [route("a", null, { is_fastest: true }), route("b", 600)]],
  ])("%sならnull", (_label, routes) => {
    expect(durationBaseline(routes)).toBeNull();
  });
});

describe("durationDifferenceLabel", () => {
  it.each([
    [629, null], // 差が丸めて1分に満たない
    [630, "+1分"], // 半分ちょうどからは1分
    [420, "−3分"], // 基準線より速く見積もられた
  ])("所要時間%i秒（基準線600秒）は%s", (seconds, expected) => {
    expect(durationDifferenceLabel(route("a", seconds), 600)).toBe(expected);
  });

  it("基準線が無い・自分の所要時間が無いならnull", () => {
    expect(durationDifferenceLabel(route("a", 900), null)).toBeNull();
    expect(durationDifferenceLabel(route("a", null), 600)).toBeNull();
  });
});

describe("orderGenerated", () => {
  it("最速の印の1本を先頭に、残りを所要時間の短い順に並べ、所要時間の無い候補は末尾、同着は受け取った並びを保つ", () => {
    const routes = [
      route("a", 900),
      route("none", null),
      route("fastest", 700, { is_fastest: true }),
      route("b", 600),
      route("c", 900),
    ];
    expect(orderGenerated(routes).map((r) => r.id)).toEqual(["fastest", "b", "a", "c", "none"]);
  });
});

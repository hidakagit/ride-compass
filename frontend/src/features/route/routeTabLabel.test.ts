// @vitest-environment node
/**
 * `features/route/routeTabLabel.ts`——「ルート結果」の一覧の並び・群・名前と、基準線（最も早い候補）との差の表記。
 * - `routeListEntries`: 最速の1本（最速の1本を含める生成だけ）・残りの生成候補（1からの番号。経由地ルートは方位の
 *   名前）・合成で作ったルート（「合成N」）の順に、群を付けて置く
 * - `fastestRouteId`・`fastestDurationSeconds`: 2件以上のうち所要時間が最も短い候補（同着は先の方）
 * - `extraDurationLabel`: 基準線より丸めて1分以上余計にかかる分を「+N分」で書く
 * - `orderByDuration`: 所要時間の短い順。所要時間の無い候補は末尾、同着は受け取った並び
 *
 * ここで見ないもの:
 * - 一覧・タブへの描き方（群の印・区切りの線） → `RouteOutcome/RouteOutcome.test.tsx`
 * - 生成した候補をこの並びで結果へ渡すこと → `useRouteGeneration.test.ts`
 */
import { describe, expect, it } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import {
  extraDurationLabel,
  fastestDurationSeconds,
  fastestRouteId,
  orderByDuration,
  routeListEntries,
} from "./routeTabLabel";

function route(id: string, seconds: number | null) {
  return { id, direction_label: `${id}の方位`, estimated_duration_seconds: seconds };
}

/** 行を「id:群:名前/名前の列の文字」で並べる。 */
function entriesOf(entries: ReturnType<typeof routeListEntries<ReturnType<typeof route>>>) {
  return entries.map((e) => `${e.route.id}:${e.group}:${e.name}/${e.label}`);
}

describe("routeListEntries", () => {
  const generated = [route("a", 900), route("b", 600), route("c", 1200)];

  it("最速の1本を含めない生成で合成も無ければ、全部を生成した候補として受け取った順で1から番号を振る", () => {
    expect(entriesOf(routeListEntries(generated, [], false))).toEqual([
      "a:generated:1/1",
      "b:generated:2/2",
      "c:generated:3/3",
    ]);
  });

  it("最速の1本を含める生成なら、最も早い生成候補を最速として先頭に印だけで置き、残りに1から番号を振る", () => {
    expect(entriesOf(routeListEntries(generated, [], true))).toEqual([
      "b:fastest:最速/",
      "a:generated:1/1",
      "c:generated:2/2",
    ]);
  });

  it("合成で作ったルートは、生成した候補の後へ受け取った順に「合成N」で並び、名前の列には番号を出す", () => {
    const edits = [
      { route: route("e2", 700), number: 2 },
      { route: route("e1", 650), number: 1 },
    ];
    expect(entriesOf(routeListEntries(generated, edits, true))).toEqual([
      "b:fastest:最速/",
      "a:generated:1/1",
      "c:generated:2/2",
      "e2:spliced:合成2/2",
      "e1:spliced:合成1/1",
    ]);
  });

  it("比べる相手の無い1件だけの生成は、最速の1本を含める生成でも最速にしない", () => {
    expect(entriesOf(routeListEntries([route("a", 900)], [], true))).toEqual(["a:generated:1/1"]);
  });

  it("経由地ルートは番号の代わりに方位の名前を出す", () => {
    const waypoints = route(routeGenerateConfig.waypoints_route_id, 900);
    expect(entriesOf(routeListEntries([waypoints], [], false))).toEqual([
      `${waypoints.id}:generated:${waypoints.direction_label}/${waypoints.direction_label}`,
    ]);
  });
});

describe("fastestRouteId・fastestDurationSeconds", () => {
  it("所要時間が最も短い候補のidと所要時間", () => {
    const routes = [route("a", 900), route("b", 600), route("c", 1200)];
    expect(fastestRouteId(routes)).toBe("b");
    expect(fastestDurationSeconds(routes)).toBe(600);
  });

  it("同着なら先に来た方", () => {
    const routes = [route("a", 900), route("b", 600), route("c", 600)];
    expect(fastestRouteId(routes)).toBe("b");
  });

  it("所要時間の無い候補は比べない", () => {
    const routes = [route("a", null), route("b", 600), route("c", 900)];
    expect(fastestRouteId(routes)).toBe("b");
  });

  it.each([
    ["候補が1件", [route("a", 600)]],
    ["候補が無い", []],
    ["所要時間を持つ候補が無い", [route("a", null), route("b", null)]],
  ])("%sならnull", (_label, routes) => {
    expect(fastestRouteId(routes)).toBeNull();
    expect(fastestDurationSeconds(routes)).toBeNull();
  });
});

describe("extraDurationLabel", () => {
  it("基準線より余計にかかる分を、分へ四捨五入して「+N分」で書く", () => {
    expect(extraDurationLabel(route("a", 600 + 12 * 60), 600)).toBe("+12分");
    expect(extraDurationLabel(route("a", 600 + 107 * 60 + 29), 600)).toBe("+107分");
  });

  it("差が丸めて1分に満たなければnull、半分ちょうどからは「+1分」", () => {
    expect(extraDurationLabel(route("a", 600), 600)).toBeNull();
    expect(extraDurationLabel(route("a", 629), 600)).toBeNull();
    expect(extraDurationLabel(route("a", 630), 600)).toBe("+1分");
  });

  it("基準線が無い・自分の所要時間が無いならnull", () => {
    expect(extraDurationLabel(route("a", 900), null)).toBeNull();
    expect(extraDurationLabel(route("a", null), 600)).toBeNull();
  });
});

describe("orderByDuration", () => {
  it("所要時間の短い順に並べ、所要時間の無い候補は末尾、同着は受け取った並びを保つ", () => {
    const routes = [route("a", 900), route("none", null), route("b", 600), route("c", 900)];
    expect(orderByDuration(routes).map((r) => r.id)).toEqual(["b", "a", "c", "none"]);
  });

  it("受け取った並びは書き換えない", () => {
    const routes = [route("a", 900), route("b", 600)];
    orderByDuration(routes);
    expect(routes.map((r) => r.id)).toEqual(["a", "b"]);
  });
});

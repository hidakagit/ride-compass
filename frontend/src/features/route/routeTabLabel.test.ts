// @vitest-environment node
import { describe, expect, it } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import {
  FASTEST_ROUTE_NAME,
  extraDurationLabel,
  fastestDurationSeconds,
  fastestRouteId,
  orderByDuration,
  routeListSections,
} from "./routeTabLabel";

const route = (id: string, seconds?: number | null) => ({ id, estimated_duration_seconds: seconds });

describe("fastestRouteId（一覧の中の基準線）", () => {
  it("所要時間が最も短い候補。同着は先に来た方", () => {
    expect(fastestRouteId([route("a", 900), route("b", 600), route("c", 700)])).toBe("b");
    expect(fastestRouteId([route("a", 600), route("b", 600)])).toBe("a");
  });

  it("所要時間を持たない候補は比べない", () => {
    expect(fastestRouteId([route("a", null), route("b"), route("c", Number.NaN), route("d", 800)])).toBe("d");
  });

  it("比べる相手が無ければnull（候補が1件以下・所要時間を持つ候補が無い）", () => {
    expect(fastestRouteId([route("a", 600)])).toBeNull();
    expect(fastestRouteId([])).toBeNull();
    expect(fastestRouteId([route("a", null), route("b")])).toBeNull();
  });
});

describe("fastestDurationSeconds（基準線の所要時間）", () => {
  it("基準線の候補の所要時間。基準線が無ければnull", () => {
    expect(fastestDurationSeconds([route("a", 900), route("b", 600)])).toBe(600);
    expect(fastestDurationSeconds([route("a", 900)])).toBeNull();
  });
});

describe("extraDurationLabel（基準線より余計にかかる分）", () => {
  it("分へ四捨五入した差を「+N分」で出す", () => {
    expect(extraDurationLabel(route("x", 600 + 12 * 60), 600)).toBe("+12分");
    expect(extraDurationLabel(route("x", 600 + 90), 600)).toBe("+2分");
  });

  it("1時間以上の差も分で出す", () => {
    expect(extraDurationLabel(route("x", 600 + 107 * 60), 600)).toBe("+107分");
  });

  it("差が丸めて1分未満なら出さない（基準線自身もここに入る）", () => {
    expect(extraDurationLabel(route("x", 600), 600)).toBeNull();
    expect(extraDurationLabel(route("x", 629), 600)).toBeNull();
  });

  it("基準線か自分の所要時間が無ければ出さない", () => {
    expect(extraDurationLabel(route("x", 900), null)).toBeNull();
    expect(extraDurationLabel(route("x", null), 600)).toBeNull();
    expect(extraDurationLabel(route("x"), 600)).toBeNull();
  });
});

describe("orderByDuration（候補一覧の並び）", () => {
  const candidate = (id: string, seconds: number | null) => ({ id, estimated_duration_seconds: seconds });
  const ids = (routes: readonly { id: string }[]) => routes.map((route) => route.id);

  it("所要時間の短い順に並べ、所要時間の無い候補は末尾に置く", () => {
    const routes = [candidate("a", 3600), candidate("n", null), candidate("b", 3000), candidate("c", 4200)];
    expect(ids(orderByDuration(routes))).toEqual(["b", "a", "c", "n"]);
  });

  it("同じ所要時間なら受け取った並び（総合難易度の昇順）を保ち、元の一覧は書き換えない", () => {
    const routes = [candidate("easy", 3600), candidate("hard", 3600), candidate("fast", 3000)];
    expect(ids(orderByDuration(routes))).toEqual(["fast", "easy", "hard"]);
    expect(ids(routes)).toEqual(["easy", "hard", "fast"]);
  });
});

describe("routeListSections（一覧の見出しと名前）", () => {
  const listed = (id: string, seconds: number | null, direction_label = "") => ({
    id,
    direction_label,
    estimated_duration_seconds: seconds,
  });
  const generated = [listed("g0", 600), listed("g1", 700), listed("g2", 800)];
  const shape = (sections: ReturnType<typeof routeListSections<ReturnType<typeof listed>>>) =>
    sections.map((section) => ({
      title: section.title,
      entries: section.entries.map(
        (entry) => `${entry.route.id}:${entry.name}:${entry.nameShown ? "出す" : "出さない"}`,
      ),
    }));

  it("最速の1本を含む生成なら、最速を採用ルートの先頭に名前を出さずに置き、残りの生成候補に1から番号を振る", () => {
    expect(shape(routeListSections(generated, [], true))).toEqual([
      { title: "採用ルート", entries: [`g0:${FASTEST_ROUTE_NAME}:出さない`] },
      { title: "生成した候補", entries: ["g1:1:出す", "g2:2:出す"] },
    ]);
  });

  it("編集で作ったルートは採用ルートの最速の後へ作った順に「編集N」で並ぶ", () => {
    const edits = [
      { route: listed("e1", 500), number: 1 },
      { route: listed("e2", 900), number: 2 },
    ];
    expect(shape(routeListSections(generated, edits, true))[0].entries).toEqual([
      `g0:${FASTEST_ROUTE_NAME}:出さない`,
      "e1:編集1:出す",
      "e2:編集2:出す",
    ]);
  });

  it("最速の1本を含まない生成（周回等）で編集も無ければ、見出しを持たずに1から番号を振る", () => {
    expect(shape(routeListSections(generated, [], false))).toEqual([
      { title: null, entries: ["g0:1:出す", "g1:2:出す", "g2:3:出す"] },
    ]);
  });

  it("比べる相手の無い1件だけの生成は、最速の1本を含む生成でも見出しを分けない", () => {
    expect(shape(routeListSections([listed("g0", 600)], [], true))).toEqual([{ title: null, entries: ["g0:1:出す"] }]);
  });

  it("経由地を通るルートは番号の代わりに名前を出す", () => {
    const waypoints = listed(routeGenerateConfig.waypoints_route_id, 600, "経由地ルート");
    expect(shape(routeListSections([waypoints], [], false))[0].entries).toEqual([`${waypoints.id}:経由地ルート:出す`]);
  });
});

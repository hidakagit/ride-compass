// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  SPLICED_ROUTE_ID_PREFIX,
  extraDurationLabel,
  fastestDurationSeconds,
  fastestRouteId,
  isSplicedRoute,
} from "./routeTabLabel";

const route = (id: string, seconds?: number | null) => ({ id, estimated_duration_seconds: seconds });

describe("isSplicedRoute（区間を乗り換えて作った候補か）", () => {
  it("backendが付ける接頭辞で始まるidだけが該当する", () => {
    expect(isSplicedRoute({ id: `${SPLICED_ROUTE_ID_PREFIX}2` })).toBe(true);
    expect(isSplicedRoute({ id: "route-1" })).toBe(false);
  });
});

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

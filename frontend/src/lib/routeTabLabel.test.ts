// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  SPLICED_ROUTE_ID_PREFIX,
  extraDistanceLabel,
  isSplicedRoute,
  shortestDistanceKm,
  shortestDistanceRouteId,
} from "./routeTabLabel";

const SHORTEST = { distance_km: 18.0, is_shortest_distance: true };
const LONGER = { distance_km: 22.0, is_shortest_distance: false };

describe("shortestDistanceKm", () => {
  it("基準線となる候補の距離を返す", () => {
    expect(shortestDistanceKm([LONGER, SHORTEST])).toBe(18.0);
  });

  it("基準線が無ければnull（周回モードや最短経路を求められなかった場合）", () => {
    expect(shortestDistanceKm([LONGER, { distance_km: 25.0 }])).toBeNull();
  });
});

describe("extraDistanceLabel", () => {
  it("最短より何km余分に走るかを出す", () => {
    expect(extraDistanceLabel(LONGER, 18.0)).toBe("+4.0");
  });

  it("基準線そのものには出さない", () => {
    expect(extraDistanceLabel(SHORTEST, 18.0)).toBeNull();
  });

  it("基準線が無ければ出さない", () => {
    expect(extraDistanceLabel(LONGER, null)).toBeNull();
  });

  it("差が丸めて0.0kmになるなら出さない（0を並べても判断材料にならない）", () => {
    expect(extraDistanceLabel({ distance_km: 18.02 }, 18.0)).toBeNull();
  });

  it("最短と同じ経路でなくても距離が同じなら出さない", () => {
    expect(extraDistanceLabel({ distance_km: 18.0 }, 18.0)).toBeNull();
  });
});

describe("isSplicedRoute", () => {
  it("区間を乗り換えて作った候補を見分ける", () => {
    expect(isSplicedRoute({ id: `${SPLICED_ROUTE_ID_PREFIX}-0` })).toBe(true);
    expect(isSplicedRoute({ id: `${SPLICED_ROUTE_ID_PREFIX}-12` })).toBe(true);
  });

  it("生成候補は合成として扱わない", () => {
    // 生成候補を合成と誤判定すると、順位番号が「合成」に化けて並び順が読めなくなる
    expect(isSplicedRoute({ id: "route-00" })).toBe(false);
    expect(isSplicedRoute({ id: "route-destination-00" })).toBe(false);
    expect(isSplicedRoute({ id: "route-waypoints" })).toBe(false);
  });

  it("backendが付ける接頭辞と、フロントが組み立てるidが同じ1つの値から出る", () => {
    // 別々に書くと、片方だけ変えたときに合成ルートが一覧で見分けられなくなる
    expect(SPLICED_ROUTE_ID_PREFIX).toBe("route-spliced");
  });
});

describe("shortestDistanceRouteId", () => {
  it("一覧の中で最も距離が短い候補のidを返す", () => {
    const routes = [
      { id: "a", distance_km: 20.3 },
      { id: "b", distance_km: 16.3 },
      { id: "c", distance_km: 21.4 },
    ];

    expect(shortestDistanceRouteId(routes)).toBe("b");
  });

  it("候補が1件以下なら比べる相手が無いのでnull", () => {
    expect(shortestDistanceRouteId([{ id: "a", distance_km: 20 }])).toBeNull();
    expect(shortestDistanceRouteId([])).toBeNull();
  });
});

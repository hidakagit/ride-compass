// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  SPLICED_ROUTE_ID_PREFIX,
  extraDurationLabel,
  fastestDurationSeconds,
  isSplicedRoute,
  shortestDistanceRouteId,
} from "./routeTabLabel";

const FASTEST = { estimated_duration_seconds: 3600, is_fastest: true };
const SLOWER = { estimated_duration_seconds: 4320, is_fastest: false };

describe("fastestDurationSeconds", () => {
  it("基準線となる候補の所要時間を返す", () => {
    expect(fastestDurationSeconds([SLOWER, FASTEST])).toBe(3600);
  });

  it("基準線が無ければnull（周回モードや基準線を求められなかった場合）", () => {
    expect(fastestDurationSeconds([SLOWER, { estimated_duration_seconds: 5000 }])).toBeNull();
  });

  it("基準線が所要時間を持たなければnull", () => {
    expect(fastestDurationSeconds([{ estimated_duration_seconds: null, is_fastest: true }])).toBeNull();
  });
});

describe("extraDurationLabel", () => {
  it("基準線より何分余計にかかるかを出す", () => {
    expect(extraDurationLabel(SLOWER, 3600)).toBe("+12分");
  });

  it("基準線そのものには出さない", () => {
    expect(extraDurationLabel(FASTEST, 3600)).toBeNull();
  });

  it("基準線が無ければ出さない", () => {
    expect(extraDurationLabel(SLOWER, null)).toBeNull();
  });

  it("自分の所要時間が無ければ出さない", () => {
    expect(extraDurationLabel({ estimated_duration_seconds: null }, 3600)).toBeNull();
  });

  it("差が丸めて1分未満なら出さない（0を並べても判断材料にならない）", () => {
    expect(extraDurationLabel({ estimated_duration_seconds: 3620 }, 3600)).toBeNull();
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

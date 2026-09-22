import routeGenerateConfig from "@/types/generated/route-generate-config.json";
// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  SPLICED_ROUTE_ID_PREFIX,
  extraDurationLabel,
  fastestDurationSeconds,
  fastestRouteId,
  isSplicedRoute,
} from "./routeTabLabel";

const FASTEST = { id: "a", estimated_duration_seconds: 3600 };
const SLOWER = { id: "b", estimated_duration_seconds: 4320 };

describe("fastestRouteId", () => {
  it("一覧の中で所要時間が最小の候補を基準線にする", () => {
    expect(fastestRouteId([SLOWER, FASTEST])).toBe("a");
  });

  it("backendのis_fastestが付かない一覧（周回モード）でも基準線が決まる", () => {
    // ここが効かないと、主用途である周回モードで「最速」も「+N分」も一度も出ない。
    const loop = [
      { id: "route-00", estimated_duration_seconds: 6300 },
      { id: "route-01", estimated_duration_seconds: 5820 },
      { id: "route-02", estimated_duration_seconds: 6600 },
    ];

    expect(fastestRouteId(loop)).toBe("route-01");
  });

  it("所要時間を持たない候補は基準線の候補から外す", () => {
    expect(fastestRouteId([{ id: "a", estimated_duration_seconds: null }, SLOWER])).toBe("b");
  });

  it("同着は先に来た方（並び順は総合難易度の昇順なので、易しい方）", () => {
    const tied = [
      { id: "a", estimated_duration_seconds: 3600 },
      { id: "b", estimated_duration_seconds: 3600 },
    ];

    expect(fastestRouteId(tied)).toBe("a");
  });

  it("候補が1件以下なら比べる相手が無いのでnull", () => {
    expect(fastestRouteId([FASTEST])).toBeNull();
    expect(fastestRouteId([])).toBeNull();
  });

  it("誰も所要時間を持たなければnull", () => {
    expect(
      fastestRouteId([
        { id: "a", estimated_duration_seconds: null },
        { id: "b", estimated_duration_seconds: undefined },
      ]),
    ).toBeNull();
  });
});

describe("fastestDurationSeconds", () => {
  it("基準線となる候補の所要時間を返す", () => {
    expect(fastestDurationSeconds([SLOWER, FASTEST])).toBe(3600);
  });

  it("基準線が決まらなければnull", () => {
    expect(fastestDurationSeconds([FASTEST])).toBeNull();
  });
});

describe("extraDurationLabel", () => {
  it("基準線より何分余計にかかるかを出す", () => {
    expect(extraDurationLabel(SLOWER, 3600)).toBe("+12分");
  });

  it("基準線そのものには出さない（差が0のため）", () => {
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

});

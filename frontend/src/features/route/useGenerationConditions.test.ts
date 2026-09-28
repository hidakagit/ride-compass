/**
 * 生成の条件（`useGenerationConditions`）——「ルート設定」の入力を持ち、保存する値を読むときに今の範囲・今の項目へ揃える。
 *
 * ここで見ないもの:
 * - 重み・除外を揃える規則そのもの → `routePreferenceSync.ts`・`hardFilterSync.ts`
 * - 入力から生成リクエストを組み立てること → `useRouteGeneration.ts`
 *
 * 差し替えた部品: 軸カタログ（`useAxisCatalog`）は返す値をテストが決める（取得の通信は`useAxisCatalog`の持ち物）。
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { axisCatalogFromResponse, EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";
import { catalogEntry } from "@/testing/catalogAxes";
import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { Coordinates } from "@/types/route";

const catalog = vi.hoisted(() => ({ current: undefined as unknown }));
vi.mock("@/hooks/useAxisCatalog", () => ({ useAxisCatalog: () => catalog.current }));

import { useGenerationConditions } from "./useGenerationConditions";

const A: Coordinates = { latitude: 35, longitude: 139 };
const B: Coordinates = { latitude: 35.1, longitude: 139.1 };
const C: Coordinates = { latitude: 35.2, longitude: 139.2 };

const CATALOG: AxisCatalog = axisCatalogFromResponse(
  [catalogEntry({ axis_id: "axis_a", default_weight: 0.3 }), catalogEntry({ axis_id: "axis_b", default_weight: 0.7 })],
  {},
  {},
  [],
);

const onOriginPlace = vi.fn<(point: Coordinates) => void>();
function render() {
  return renderHook(() => useGenerationConditions({ onOriginPlace }));
}

beforeEach(() => {
  localStorage.clear();
  catalog.current = CATALOG;
  onOriginPlace.mockReset();
});

describe("周回か目的地か", () => {
  it("既定は周回で、選んだモードは開き直しても残る", () => {
    const first = render();
    expect(first.result.current.routeMode).toBe("loop");
    act(() => first.result.current.changeRouteMode("destination"));
    first.unmount();
    expect(render().result.current.routeMode).toBe("destination");
  });

  it("知らない値の保存値は捨てて周回で始める", () => {
    localStorage.setItem("ridecompass:route-mode", "round-trip");
    expect(render().result.current.routeMode).toBe("loop");
  });

  it("目的地へ切り替えたとき、何も置いていなければ次のタップで目的地を置けるようにし、周回へ戻すとやめる", () => {
    const { result } = render();
    act(() => result.current.changeRouteMode("destination"));
    expect(result.current.armedPinRole).toBe("destination");
    act(() => result.current.changeRouteMode("loop"));
    expect(result.current.armedPinRole).toBeNull();
  });

  it.each([
    ["目的地", "destination" as const],
    ["経由地", "waypoint" as const],
  ])("%sが既に置いてあれば、目的地へ切り替えても自動では置けるようにしない", (_case, role) => {
    const { result } = render();
    act(() => result.current.placePin(role, A));
    act(() => result.current.armPinRole(null));
    act(() => result.current.changeRouteMode("destination"));
    expect(result.current.armedPinRole).toBeNull();
  });

  it("周回へ切り替えても置いた地点は消さない", () => {
    const { result } = render();
    act(() => result.current.changeRouteMode("destination"));
    act(() => result.current.placePin("destination", A));
    act(() => result.current.changeRouteMode("loop"));
    expect(result.current.destination).toEqual(A);
  });
});

describe("地点の指定", () => {
  it("出発地は位置の持ち主へ渡して置く状態をやめる。目的地は置き換えて置く状態をやめる", () => {
    const { result } = render();
    act(() => result.current.armPinRole("origin"));
    act(() => result.current.placePin("origin", A));
    expect(onOriginPlace).toHaveBeenCalledWith(A);
    expect(result.current.armedPinRole).toBeNull();

    act(() => result.current.armPinRole("destination"));
    act(() => result.current.placePin("destination", B));
    act(() => result.current.armPinRole("destination"));
    act(() => result.current.placePin("destination", C));
    expect(result.current.destination).toEqual(C);
    expect(result.current.armedPinRole).toBeNull();
  });

  it("経由地は置いた順に足し、置いたあとも続けて置ける", () => {
    const { result } = render();
    act(() => result.current.armPinRole("waypoint"));
    act(() => result.current.placePin("waypoint", A));
    act(() => result.current.placePin("waypoint", B));
    expect(result.current.waypoints).toEqual([A, B]);
    expect(result.current.armedPinRole).toBe("waypoint");
  });

  it("経由地は生成が受け付ける数まで置け、そこで置く状態をやめ、それより多くは置かない", () => {
    const { result } = render();
    const limit = routeGenerateConfig.max_waypoints;
    act(() => result.current.armPinRole("waypoint"));
    for (let i = 0; i < limit - 1; i++) act(() => result.current.placePin("waypoint", A));
    expect(result.current.armedPinRole).toBe("waypoint");
    act(() => result.current.placePin("waypoint", B));
    expect(result.current.armedPinRole).toBeNull();
    act(() => result.current.placePin("waypoint", C));
    expect(result.current.waypoints).toHaveLength(limit);
    expect(result.current.waypoints.at(-1)).toEqual(B);
  });

  it("経由地は位置を指して動かす・消す・まとめて消すことができ、目的地も消せる", () => {
    const { result } = render();
    act(() => result.current.placePin("waypoint", A));
    act(() => result.current.placePin("waypoint", B));
    act(() => result.current.moveWaypoint(0, C));
    expect(result.current.waypoints).toEqual([C, B]);
    act(() => result.current.removeWaypoint(1));
    expect(result.current.waypoints).toEqual([C]);
    act(() => result.current.clearWaypoints());
    expect(result.current.waypoints).toEqual([]);

    act(() => result.current.placePin("destination", A));
    act(() => result.current.clearDestination());
    expect(result.current.destination).toBeNull();
  });

  it("地点は保存しない（開き直すと置いていない状態から始まる）", () => {
    const first = render();
    act(() => first.result.current.placePin("waypoint", A));
    act(() => first.result.current.placePin("destination", B));
    first.unmount();
    const second = render();
    expect(second.result.current.waypoints).toEqual([]);
    expect(second.result.current.destination).toBeNull();
  });
});

describe("距離と候補数", () => {
  it("入力した値は文字列のまま持ち、開き直しても残る", () => {
    const first = render();
    act(() => first.result.current.setDistanceInput("45"));
    act(() => first.result.current.setMaxRoutesInput("3"));
    first.unmount();
    const second = render();
    expect(second.result.current.distanceInput).toBe("45");
    expect(second.result.current.maxRoutesInput).toBe("3");
  });

  it("保存値が無ければ距離30km・候補数は既定の数で始める", () => {
    const { result } = render();
    expect(result.current.distanceInput).toBe("30");
    expect(result.current.maxRoutesInput).toBe(String(routeGenerateConfig.default_max_routes));
  });

  it.each([
    ["1kmより短い", "0.5"],
    ["上限より長い", String(routeGenerateConfig.max_distance_km + 1)],
    ["数でない", "far"],
  ])("距離の保存値が%sなら捨てる", (_case, stored) => {
    localStorage.setItem("ridecompass:distance-km", stored);
    expect(render().result.current.distanceInput).toBe("30");
  });

  it("距離の保存値は範囲の端ちょうどなら受け入れる", () => {
    localStorage.setItem("ridecompass:distance-km", String(routeGenerateConfig.max_distance_km));
    expect(render().result.current.distanceInput).toBe(String(routeGenerateConfig.max_distance_km));
  });

  it.each([
    ["0件", "0"],
    ["上限より多い", String(routeGenerateConfig.max_routes + 1)],
    ["整数でない", "2.5"],
  ])("候補数の保存値が%sなら捨てる", (_case, stored) => {
    localStorage.setItem("ridecompass:max-routes", stored);
    expect(render().result.current.maxRoutesInput).toBe(String(routeGenerateConfig.default_max_routes));
  });
});

describe("重み", () => {
  it("画面が読む重みは公開軸へ揃えた値（増えた軸は既定で補い、消えた軸は外す）で、保存値は書き換えない", () => {
    localStorage.setItem("ridecompass:route-preference", JSON.stringify({ axis_a: 0.9, retired_axis: 0.1 }));
    const { result } = render();
    expect(result.current.routePreference).toEqual({ axis_a: 0.9, axis_b: 0.7 });
    expect(JSON.parse(localStorage.getItem("ridecompass:route-preference")!)).toEqual({
      axis_a: 0.9,
      retired_axis: 0.1,
    });
  });

  it("軸カタログが届くまでは揃えない（届いていない間に揃えると、保存した重みを全部消す）", () => {
    catalog.current = EMPTY_CATALOG;
    localStorage.setItem("ridecompass:route-preference", JSON.stringify({ axis_a: 0.9 }));
    expect(render().result.current.routePreference).toEqual({ axis_a: 0.9 });
  });

  it("送る重みは、上書きを有効にしていて軸カタログが届いているときだけ揃えた値で、それ以外はnull", () => {
    const { result, rerender } = render();
    expect(result.current.routePreferenceToSend).toBeNull();
    act(() => result.current.setWeightOverrideEnabled(true));
    expect(result.current.routePreferenceToSend).toEqual({ axis_a: 0.3, axis_b: 0.7 });
    catalog.current = EMPTY_CATALOG;
    rerender();
    expect(result.current.routePreferenceToSend).toBeNull();
  });

  it("動かした重みと上書きの有無は開き直しても残る", () => {
    const first = render();
    act(() => first.result.current.setWeightOverrideEnabled(true));
    act(() => first.result.current.setRoutePreference({ axis_a: 1, axis_b: 0 }));
    first.unmount();
    const second = render();
    expect(second.result.current.weightOverrideEnabled).toBe(true);
    expect(second.result.current.routePreference).toEqual({ axis_a: 1, axis_b: 0 });
  });
});

describe("除外", () => {
  const [FIRST] = Object.keys(DEFAULT_HARD_FILTERS);

  it("保存値が無ければ既定の除外で始め、変えた除外は開き直しても残る", () => {
    const first = render();
    expect(first.result.current.hardFilters).toEqual(DEFAULT_HARD_FILTERS);
    const flipped = { ...DEFAULT_HARD_FILTERS, [FIRST]: !DEFAULT_HARD_FILTERS[FIRST] };
    act(() => first.result.current.setHardFilters(flipped));
    first.unmount();
    expect(render().result.current.hardFilters).toEqual(flipped);
  });

  it("保存値に今は無い項目が混じっていても、今の項目へ揃えて読む", () => {
    localStorage.setItem(
      "ridecompass:hard-filters",
      JSON.stringify({ [FIRST]: !DEFAULT_HARD_FILTERS[FIRST], retired_filter: true }),
    );
    expect(render().result.current.hardFilters).toEqual({
      ...DEFAULT_HARD_FILTERS,
      [FIRST]: !DEFAULT_HARD_FILTERS[FIRST],
    });
  });

  it("読めない保存値は捨てて既定の除外で始める", () => {
    localStorage.setItem("ridecompass:hard-filters", "{broken");
    expect(render().result.current.hardFilters).toEqual(DEFAULT_HARD_FILTERS);
  });
});

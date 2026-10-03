import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import { fixedRouteCount, useRouteFormSubmit, type RouteMode } from "./useRouteFormSubmit";

function submit(options: {
  distance?: string;
  routeMode?: RouteMode;
  waypointCount?: number;
  destinationSet?: boolean;
  originKnown?: boolean;
}) {
  const { result } = renderHook(() =>
    useRouteFormSubmit({
      distance: "20",
      routeMode: "loop",
      waypointCount: 0,
      destinationSet: false,
      originKnown: true,
      ...options,
    }),
  );
  let distanceKm: number | null = null;
  act(() => {
    distanceKm = result.current.check();
  });
  return { error: result.current.error, distanceKm, result };
}

describe("fixedRouteCount（候補数の指定を使わない生成の、決まった候補数）", () => {
  it("経由地を伴う目的地だけがbackendの決まった数。周回（経由地は送らない）と経由地の無い目的地は指定を使う", () => {
    expect(fixedRouteCount("destination", 1)).toBe(routeGenerateConfig.routes_with_waypoints);
    expect(fixedRouteCount("destination", 0)).toBeNull();
    expect(fixedRouteCount("loop", 2)).toBeNull();
  });
});

describe("useRouteFormSubmit 周回", () => {
  it("入力の距離で生成する", () => {
    const { error, distanceKm } = submit({ distance: "25.5" });
    expect(error).toBeNull();
    expect(distanceKm).toBe(25.5);
  });
});

describe("useRouteFormSubmit 出発地", () => {
  it.each(["loop", "destination"] as const)(
    "出発地が仮の地点のままなら（%s）、生成せずに位置情報の許可か地図での指定を促す",
    (routeMode) => {
      const { error, distanceKm } = submit({ routeMode, destinationSet: true, originKnown: false });
      expect(error).toBe(
        "現在地が分かりません。位置情報を許可するか、出発地の「地図で選ぶ」を押して地図をタップしてください。",
      );
      expect(distanceKm).toBeNull();
    },
  );
});

describe("useRouteFormSubmit 目的地", () => {
  it("目的地も経由地も無ければ生成せず、地図で指定するよう促す", () => {
    const { error, distanceKm } = submit({ routeMode: "destination" });
    expect(error).toBe("地図をタップして目的地か経由地を指定してください。");
    expect(distanceKm).toBeNull();
  });

  it("目的地か経由地があれば、距離を見ずに生成する（距離は地図の点から画面側が決める）", () => {
    expect(submit({ routeMode: "destination", destinationSet: true, distance: "" }).distanceKm).toBe(0);
    expect(submit({ routeMode: "destination", waypointCount: 1, distance: "" }).distanceKm).toBe(0);
  });

  it("地点を置いて押し直すと、文言が消えて生成する", () => {
    let destinationSet = false;
    const { result, rerender } = renderHook(() =>
      useRouteFormSubmit({
        distance: "20",
        routeMode: "destination",
        waypointCount: 0,
        destinationSet,
        originKnown: true,
      }),
    );
    act(() => void result.current.check());
    expect(result.current.error).not.toBeNull();
    destinationSet = true;
    rerender();
    let distanceKm: number | null = null;
    act(() => {
      distanceKm = result.current.check();
    });
    expect(result.current.error).toBeNull();
    expect(distanceKm).toBe(0);
  });
});

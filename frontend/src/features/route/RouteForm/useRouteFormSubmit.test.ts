import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import { fixedRouteCount, useRouteFormSubmit, type RouteMode } from "./useRouteFormSubmit";

function submit(options: {
  distance?: string;
  routeMode?: RouteMode;
  waypointCount?: number;
  destinationSet?: boolean;
  originKnown?: boolean;
}) {
  const onGenerate = vi.fn();
  const { result } = renderHook(() =>
    useRouteFormSubmit({
      distance: "20",
      routeMode: "loop",
      waypointCount: 0,
      destinationSet: false,
      originKnown: true,
      ...options,
      onGenerate,
    }),
  );
  act(() => result.current.handleSubmit());
  return { error: result.current.error, onGenerate, result };
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
    const { error, onGenerate } = submit({ distance: "25.5" });
    expect(error).toBeNull();
    expect(onGenerate).toHaveBeenCalledWith(25.5);
  });
});

describe("useRouteFormSubmit 出発地", () => {
  it.each(["loop", "destination"] as const)(
    "出発地が仮の地点のままなら（%s）、生成せずに位置情報の許可か地図での指定を促す",
    (routeMode) => {
      const { error, onGenerate } = submit({ routeMode, destinationSet: true, originKnown: false });
      expect(error).toBe("現在地が分かりません。位置情報を許可するか、地図で出発地を選んでください。");
      expect(onGenerate).not.toHaveBeenCalled();
    },
  );
});

describe("useRouteFormSubmit 目的地", () => {
  it("目的地も経由地も無ければ生成せず、地図で指定するよう促す", () => {
    const { error, onGenerate } = submit({ routeMode: "destination" });
    expect(error).toBe("地図をタップして目的地か経由地を指定してください。");
    expect(onGenerate).not.toHaveBeenCalled();
  });

  it("目的地か経由地があれば、距離を見ずに生成する（距離は地図の点から画面側が決める）", () => {
    expect(submit({ routeMode: "destination", destinationSet: true, distance: "" }).onGenerate).toHaveBeenCalledWith(0);
    expect(submit({ routeMode: "destination", waypointCount: 1, distance: "" }).onGenerate).toHaveBeenCalledWith(0);
  });

  it("地点を置いて押し直すと、文言が消えて生成する", () => {
    const onGenerate = vi.fn();
    let destinationSet = false;
    const { result, rerender } = renderHook(() =>
      useRouteFormSubmit({
        distance: "20",
        routeMode: "destination",
        waypointCount: 0,
        destinationSet,
        originKnown: true,
        onGenerate,
      }),
    );
    act(() => result.current.handleSubmit());
    expect(result.current.error).not.toBeNull();
    destinationSet = true;
    rerender();
    act(() => result.current.handleSubmit());
    expect(result.current.error).toBeNull();
    expect(onGenerate).toHaveBeenCalledWith(0);
  });
});

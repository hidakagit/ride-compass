import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import { isMaxRoutesRelevant, useRouteFormSubmit, type RouteMode } from "./useRouteFormSubmit";

const MAX_DISTANCE_KM = routeGenerateConfig.max_distance_km;
const MAX_ROUTES = routeGenerateConfig.max_routes;

function submit(options: {
  distance?: string;
  maxRoutes?: string;
  routeMode?: RouteMode;
  waypointCount?: number;
  destinationSet?: boolean;
}) {
  const onGenerate = vi.fn();
  const { result } = renderHook(() =>
    useRouteFormSubmit({
      distance: "20",
      maxRoutes: "3",
      routeMode: "loop",
      waypointCount: 0,
      destinationSet: false,
      ...options,
      onGenerate,
    }),
  );
  act(() => result.current.handleSubmit());
  return { error: result.current.error, onGenerate, result };
}

describe("isMaxRoutesRelevant（候補数が生成結果へ効くか）", () => {
  it("周回と、経由地の無い目的地では効く。経由地を伴う目的地では効かない（backendが1件へ固定する）", () => {
    expect(isMaxRoutesRelevant("loop", 0)).toBe(true);
    expect(isMaxRoutesRelevant("loop", 2)).toBe(true);
    expect(isMaxRoutesRelevant("destination", 0)).toBe(true);
    expect(isMaxRoutesRelevant("destination", 1)).toBe(false);
  });
});

describe("useRouteFormSubmit 周回", () => {
  it("距離と候補数が正しければ、その距離で生成する", () => {
    const { error, onGenerate } = submit({ distance: "25.5", maxRoutes: "4" });
    expect(error).toBeNull();
    expect(onGenerate).toHaveBeenCalledWith(25.5);
  });

  it("距離が数値でない・0以下・上限を超えるなら生成せず、それぞれの文言を出す", () => {
    for (const [distance, message] of [
      ["", "距離は数値で入力してください。"],
      ["abc", "距離は数値で入力してください。"],
      ["0", "距離は0より大きい値を入力してください。"],
      [String(MAX_DISTANCE_KM + 1), `距離は${MAX_DISTANCE_KM}km以下で入力してください。`],
    ]) {
      const { error, onGenerate } = submit({ distance });
      expect(error).toBe(message);
      expect(onGenerate).not.toHaveBeenCalled();
    }
    expect(submit({ distance: String(MAX_DISTANCE_KM) }).error).toBeNull();
  });

  it("候補数が整数でない・範囲の外なら生成せず、それぞれの文言を出す", () => {
    for (const [maxRoutes, message] of [
      ["", "候補数は整数で入力してください。"],
      ["2.5", "候補数は整数で入力してください。"],
      ["0", `候補数は1〜${MAX_ROUTES}件で入力してください。`],
      [String(MAX_ROUTES + 1), `候補数は1〜${MAX_ROUTES}件で入力してください。`],
    ]) {
      const { error, onGenerate } = submit({ maxRoutes });
      expect(error).toBe(message);
      expect(onGenerate).not.toHaveBeenCalled();
    }
  });

  it("候補数は1件と上限ちょうどを受け付ける", () => {
    expect(submit({ maxRoutes: "1" }).error).toBeNull();
    expect(submit({ maxRoutes: String(MAX_ROUTES) }).error).toBeNull();
  });

  it("距離と候補数の両方が誤っていれば、距離の文言を出す", () => {
    expect(submit({ distance: "0", maxRoutes: "0" }).error).toBe("距離は0より大きい値を入力してください。");
  });

  it("誤りを直して押し直すと、文言が消えて生成する", () => {
    const onGenerate = vi.fn();
    let distance = "0";
    const { result, rerender } = renderHook(() =>
      useRouteFormSubmit({
        distance,
        maxRoutes: "3",
        routeMode: "loop",
        waypointCount: 0,
        destinationSet: false,
        onGenerate,
      }),
    );
    act(() => result.current.handleSubmit());
    expect(result.current.error).not.toBeNull();
    distance = "10";
    rerender();
    act(() => result.current.handleSubmit());
    expect(result.current.error).toBeNull();
    expect(onGenerate).toHaveBeenCalledWith(10);
  });
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

  it("候補数は、効くとき（経由地が無い）だけ確かめる", () => {
    expect(submit({ routeMode: "destination", destinationSet: true, maxRoutes: "0" }).error).toBe(
      `候補数は1〜${MAX_ROUTES}件で入力してください。`,
    );
    const withWaypoint = submit({ routeMode: "destination", destinationSet: true, waypointCount: 1, maxRoutes: "0" });
    expect(withWaypoint.error).toBeNull();
    expect(withWaypoint.onGenerate).toHaveBeenCalledWith(0);
  });
});

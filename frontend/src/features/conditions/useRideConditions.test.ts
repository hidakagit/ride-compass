/**
 * 走行条件（`useRideConditions`）——走行方位・出発時刻・想定速度を1つの値にまとめ、想定速度だけを保存する。
 *
 * 出発時刻の追従（5分刻みの「今」・選んだ時刻の固定）は`useDepartureTime`が持つ（`useDepartureTime.test.ts`）。
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import { useRideConditions } from "./useRideConditions";

const SPEED_KEY = "ridecompass:assumed-speed-kmh";

beforeEach(() => {
  localStorage.clear();
});

describe("想定速度の保存", () => {
  it("変えた速度は開き直しても同じ値で、走行条件にも同じ値が乗る", () => {
    const first = renderHook(() => useRideConditions());
    const speed = routeGenerateConfig.min_assumed_speed_kmh + 1;
    act(() => first.result.current.setSpeedKmh(speed));
    expect(first.result.current.ride.speedKmh).toBe(speed);
    first.unmount();

    const second = renderHook(() => useRideConditions());
    expect(second.result.current.speedKmh).toBe(speed);
  });

  it.each([
    ["範囲の下限より遅い", String(routeGenerateConfig.min_assumed_speed_kmh - 1)],
    ["範囲の上限より速い", String(routeGenerateConfig.max_assumed_speed_kmh + 1)],
    ["整数でない", String(routeGenerateConfig.min_assumed_speed_kmh + 0.5)],
  ])("保存値が%sなら捨てて既定の速度で始める", (_case, stored) => {
    localStorage.setItem(SPEED_KEY, stored);
    const { result } = renderHook(() => useRideConditions());
    expect(result.current.speedKmh).toBe(routeGenerateConfig.default_assumed_speed_kmh);
  });

  it("範囲の端ちょうどの保存値は受け入れる", () => {
    localStorage.setItem(SPEED_KEY, String(routeGenerateConfig.max_assumed_speed_kmh));
    const { result } = renderHook(() => useRideConditions());
    expect(result.current.speedKmh).toBe(routeGenerateConfig.max_assumed_speed_kmh);
  });
});

describe("走行条件の値", () => {
  it("走行方位は保存せず0から始まり、変えると走行条件に乗る。出発時刻は出発時刻の値と同じ", () => {
    const first = renderHook(() => useRideConditions());
    expect(first.result.current.ride).toEqual({
      bearingDeg: 0,
      at: first.result.current.departure.at,
      speedKmh: routeGenerateConfig.default_assumed_speed_kmh,
    });
    act(() => first.result.current.setBearingDeg(135));
    expect(first.result.current.ride.bearingDeg).toBe(135);
    first.unmount();

    expect(renderHook(() => useRideConditions()).result.current.bearingDeg).toBe(0);
  });

  it("どれも変わらない間は同じ値を返す（読み手が描き直しのたびに取り直さない）", () => {
    const { result, rerender } = renderHook(() => useRideConditions());
    const before = result.current.ride;
    rerender();
    expect(result.current.ride).toBe(before);
  });
});

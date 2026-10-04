/**
 * 生成の前の検証（`RouteForm/useRouteFormSubmit.ts`）——出発地が仮の地点のままなら、どちらのモードでも生成せずに
 * 位置情報か地図での指定を促す。目的地モードで地点が1つも無ければ、地図での指定を促す。通れば送る距離（周回は
 * 入力の距離、目的地は0）を返し、前の文言を消す。候補数の指定を使わない生成の決まった数（`fixedRouteCount`）も持つ。
 *
 * ここで見ないもの:
 * - 文言を出す場所（「ルート結果」欄・モバイルの「ルート設定」シート） → `RouteOutcome/RouteOutcome.test.tsx`・`app/page.test.tsx`
 * - 検証を通った値で何を送るか（目的地の距離・候補数の決まった数を送ること） → `useRouteGeneration.test.ts`
 * - 候補数のステッパーを押せなくする表示 → `RouteForm/RouteForm.test.tsx`
 * - 距離・候補数の値域 → 検証しない（入力はスライダー・ステッパーで、保存値は読むときに範囲の外を捨てる。
 *   `useGenerationConditions.test.ts`）
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import { fixedRouteCount, type RouteMode, useRouteFormSubmit } from "./useRouteFormSubmit";

const ORIGIN_UNKNOWN =
  "現在地が分かりません。位置情報を許可するか、出発地の「地図で選ぶ」を押して地図をタップしてください。";
const NO_POINT = "地図をタップして目的地か経由地を指定してください。";

interface Options {
  distance: string;
  routeMode: RouteMode;
  waypointCount: number;
  destinationSet: boolean;
  originKnown: boolean;
}

const LOOP: Options = { distance: "42", routeMode: "loop", waypointCount: 0, destinationSet: false, originKnown: true };

function renderSubmit(options: Options) {
  return renderHook((props: Options) => useRouteFormSubmit(props), { initialProps: options });
}

function check(result: { current: ReturnType<typeof useRouteFormSubmit> }) {
  let distance: number | null = null;
  act(() => {
    distance = result.current.check();
  });
  return distance;
}

describe("fixedRouteCount", () => {
  it("経由地を伴う目的地だけがbackendの決まった数で、周回と経由地の無い目的地は指定を使う", () => {
    expect(fixedRouteCount("destination", 1)).toBe(routeGenerateConfig.routes_with_waypoints);
    expect(fixedRouteCount("destination", 0)).toBeNull();
    expect(fixedRouteCount("loop", 2)).toBeNull();
  });
});

describe("useRouteFormSubmit", () => {
  it("押すまでは文言を出さない", () => {
    const { result } = renderSubmit({ ...LOOP, originKnown: false });

    expect(result.current.error).toBeNull();
  });

  it("周回は入力の距離を数にして返す", () => {
    const { result } = renderSubmit(LOOP);

    expect(check(result)).toBe(42);
    expect(result.current.error).toBeNull();
  });

  it.each<RouteMode>(["loop", "destination"])(
    "出発地が仮の地点のままなら（%s）、地点の有無に関わらず生成せず、位置情報の許可か地図での指定を促す",
    (routeMode) => {
      const { result } = renderSubmit({ ...LOOP, routeMode, destinationSet: true, originKnown: false });

      expect(check(result)).toBeNull();
      expect(result.current.error).toBe(ORIGIN_UNKNOWN);
    },
  );

  it("目的地モードで目的地も経由地も無ければ生成せず、地図での指定を促す", () => {
    const { result } = renderSubmit({ ...LOOP, routeMode: "destination" });

    expect(check(result)).toBeNull();
    expect(result.current.error).toBe(NO_POINT);
  });

  it.each([
    { label: "目的地だけ", waypointCount: 0, destinationSet: true },
    { label: "経由地だけ", waypointCount: 2, destinationSet: false },
  ])("目的地モードは「$label」でも生成し、距離は送らない（0を返す）", ({ waypointCount, destinationSet }) => {
    const { result } = renderSubmit({ ...LOOP, routeMode: "destination", waypointCount, destinationSet });

    expect(check(result)).toBe(0);
    expect(result.current.error).toBeNull();
  });

  it("文言は押し直すまで残り、地点を置いて押し直すと消えて生成する", () => {
    const { result, rerender } = renderSubmit({ ...LOOP, routeMode: "destination" });
    check(result);

    rerender({ ...LOOP, routeMode: "destination", destinationSet: true });
    expect(result.current.error).toBe(NO_POINT);

    expect(check(result)).toBe(0);
    expect(result.current.error).toBeNull();
  });
});

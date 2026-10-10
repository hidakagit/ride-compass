/**
 * 生成の前の検証（`RouteForm/useRouteFormSubmit.ts`）——出発地が仮の地点のままなら、どちらのモードでも生成せずに
 * 位置情報か地図での指定を促す。目的地モードで地点が1つも無ければ、地図での指定を促す。通れば送る距離（周回は
 * 入力の距離、目的地は0）を返し、前の文言を消す。
 *
 * ここで見ないもの:
 * - 文言を出す場所（「ルート結果」欄・モバイルの「ルート設定」シート） → `RouteOutcome/RouteOutcome.test.tsx`・`app/page.test.tsx`
 * - 検証を通った値で何を送るか（目的地の距離・候補数） → `useRouteGeneration.test.ts`
 * - 候補数のステッパーを押せなくする表示 → `RouteForm/RouteForm.test.tsx`
 * - 距離・候補数の値域 → 検証しない（入力はスライダー・ステッパーで、保存値は読むときに範囲の外を捨てる。
 *   `useGenerationConditions.test.ts`）
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type RouteMode, useRouteFormSubmit } from "./useRouteFormSubmit";

const ORIGIN_UNKNOWN =
  "現在地が分かりません。位置情報を許可するか、「出発地を地図で選ぶ」を押して地図をタップしてください。";
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

describe("useRouteFormSubmit", () => {
  it("周回は入力の距離を数にして返す", () => {
    const { result } = renderSubmit(LOOP);

    expect(check(result)).toBe(42);
  });

  it("出発地が仮の地点のままなら、押すまでは文言を出さず、押すと生成せずに位置情報の許可か地図での指定を促す", () => {
    const { result } = renderSubmit({ ...LOOP, originKnown: false });
    expect(result.current.error).toBeNull();

    expect(check(result)).toBeNull();
    expect(result.current.error).toBe(ORIGIN_UNKNOWN);
  });

  it("目的地モードは経由地だけでも生成し、距離は送らない（0を返す）", () => {
    const { result } = renderSubmit({ ...LOOP, routeMode: "destination", waypointCount: 2 });

    expect(check(result)).toBe(0);
  });

  it("目的地モードで目的地も経由地も無ければ生成せず、地図での指定を促す。文言は押し直すまで残り、目的地を置いて押し直すと消えて生成する", () => {
    const { result, rerender } = renderSubmit({ ...LOOP, routeMode: "destination" });
    expect(check(result)).toBeNull();
    expect(result.current.error).toBe(NO_POINT);

    rerender({ ...LOOP, routeMode: "destination", destinationSet: true });
    expect(result.current.error).toBe(NO_POINT);

    expect(check(result)).toBe(0);
    expect(result.current.error).toBeNull();
  });
});

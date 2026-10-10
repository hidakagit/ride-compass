/**
 * 生成の前の検証（`RouteForm/useRouteFormSubmit.ts`）——出発地が仮の地点のままなら生成せずに
 * 位置情報か地図での指定を促す。全長の目標を決めず経由地も目的地も無ければ、作るものが無いのでそのどれかを促す。
 * 通れば前の文言を消す。
 *
 * ここで見ないもの:
 * - 文言を出す場所（「ルート結果」欄・モバイルの「ルート設定」シート） → `RouteOutcome/RouteOutcome.test.tsx`・`app/page.test.tsx`
 * - 検証を通った値で何を送るか（距離・経由地・目的地・候補数） → `useRouteGeneration.test.ts`
 * - 候補数のステッパーを押せなくする表示 → `RouteForm/RouteForm.test.tsx`
 * - 距離・候補数の値域 → 検証しない（入力はスライダー・ステッパーで、保存値は読むときに範囲の外を捨てる。
 *   `useGenerationConditions.test.ts`）
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useRouteFormSubmit } from "./useRouteFormSubmit";

const ORIGIN_UNKNOWN =
  "現在地が分かりません。位置情報を許可するか、「出発地を地図で選ぶ」を押して地図をタップしてください。";
const NOTHING_TO_MAKE = "「全長の目標を決める」を押すか、経由地・目的地を置いてください。";

interface Options {
  distanceTargeted: boolean;
  waypointCount: number;
  destinationSet: boolean;
  originKnown: boolean;
}

const LOOP: Options = { distanceTargeted: true, waypointCount: 0, destinationSet: false, originKnown: true };
const NO_DISTANCE: Options = { ...LOOP, distanceTargeted: false };

function renderSubmit(options: Options) {
  return renderHook((props: Options) => useRouteFormSubmit(props), { initialProps: options });
}

function check(result: { current: ReturnType<typeof useRouteFormSubmit> }) {
  let passed: boolean | undefined;
  act(() => {
    passed = result.current.check();
  });
  return passed;
}

describe("useRouteFormSubmit", () => {
  it("全長の目標を決めていれば、出発地が分かるだけで生成する", () => {
    const { result } = renderSubmit(LOOP);

    expect(check(result)).toBe(true);
  });

  it("出発地が仮の地点のままなら、押すまでは文言を出さず、押すと生成せずに位置情報の許可か地図での指定を促す", () => {
    const { result } = renderSubmit({ ...LOOP, originKnown: false });
    expect(result.current.error).toBeNull();

    expect(check(result)).toBe(false);
    expect(result.current.error).toBe(ORIGIN_UNKNOWN);
  });

  it.each([
    { label: "経由地だけ", options: { ...NO_DISTANCE, waypointCount: 2 } },
    { label: "目的地だけ", options: { ...NO_DISTANCE, destinationSet: true } },
  ])("全長の目標を決めなくても、$labelがあれば生成する", ({ options }) => {
    const { result } = renderSubmit(options);

    expect(check(result)).toBe(true);
  });

  it("全長の目標を決めず経由地も目的地も無ければ生成せず、そのどれかを促す。文言は押し直すまで残り、目的地を置いて押し直すと消えて生成する", () => {
    const { result, rerender } = renderSubmit(NO_DISTANCE);
    expect(check(result)).toBe(false);
    expect(result.current.error).toBe(NOTHING_TO_MAKE);

    rerender({ ...NO_DISTANCE, destinationSet: true });
    expect(result.current.error).toBe(NOTHING_TO_MAKE);

    expect(check(result)).toBe(true);
    expect(result.current.error).toBeNull();
  });
});

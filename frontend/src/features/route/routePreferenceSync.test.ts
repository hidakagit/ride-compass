// @vitest-environment node
/**
 * `features/route/routePreferenceSync.ts`——重みを軸カタログの公開軸へ揃える。
 * - `alignRoutePreference`: カタログに増えた軸は既定の重みで補い、消えた軸は外す。カタログが届くまでは揃えない。
 *   揃える必要が無ければ渡した値をそのまま（同じ参照で）返す
 * - `routePreferenceToSend`: 重みを上書きしていて、カタログが届いているときだけ重みを送る
 *
 * ここで見ないもの:
 * - 読んだ重みをこの関数へ1回だけ通すこと・保存値の読み書き → `useGenerationConditions.test.ts`
 */
import { describe, expect, it } from "vitest";

import { alignRoutePreference, routePreferenceToSend } from "./routePreferenceSync";

const DEFAULTS = { a: 0.5, b: 0.5 };

describe("alignRoutePreference", () => {
  it("カタログが届くまでは、軸が0件でも保存した重みを消さずにそのまま返す", () => {
    const stored = { a: 0.3, stale: 0.7 };
    expect(alignRoutePreference(stored, { loaded: false, defaultWeights: {} })).toBe(stored);
  });

  it("キーがカタログの公開軸と同じなら、渡した値をそのまま返す", () => {
    const stored = { b: 0.1, a: 0.9 };
    expect(alignRoutePreference(stored, { loaded: true, defaultWeights: DEFAULTS })).toBe(stored);
  });

  it("カタログに増えた軸は既定の重みで補い、ほかの軸の重みは変えない", () => {
    expect(alignRoutePreference({ a: 0.2 }, { loaded: true, defaultWeights: DEFAULTS })).toEqual({ a: 0.2, b: 0.5 });
  });

  it("カタログから消えた軸は外し、渡した値は書き換えない", () => {
    const stored = { a: 0.2, b: 0.3, stale: 0.5 };
    expect(alignRoutePreference(stored, { loaded: true, defaultWeights: DEFAULTS })).toEqual({ a: 0.2, b: 0.3 });
    expect(stored).toEqual({ a: 0.2, b: 0.3, stale: 0.5 });
  });
});

describe("routePreferenceToSend", () => {
  const aligned = { a: 0.2, b: 0.8 };

  it.each([
    ["上書きしていて、カタログが届いていれば、揃えた重みを送る", true, true, aligned],
    ["上書きしていなければ送らない", true, false, null],
    ["カタログが届いていなければ送らない", false, true, null],
  ])("%s", (_label, catalogLoaded, overrideEnabled, expected) => {
    expect(routePreferenceToSend(aligned, catalogLoaded, overrideEnabled)).toBe(expected);
  });
});

// @vitest-environment node
/**
 * `features/route/difficultyLoadBar.ts`——難易度の帯の高さ。
 * - `baselineDistanceKm`: 高さ1.0にする距離。一覧の中で距離が正の候補のうち最も短いもの
 * - `loadBarHeightRatio`: 基準に対する距離の比を高さにする。1.0より低くせず、上限で頭打ちにし、小数2桁へ丸める
 *
 * ここで見ないもの:
 * - 一覧の候補を渡すこと・高さを帯へ当てること → `RouteOutcome/RouteOutcome.test.tsx`
 */
import { describe, expect, it } from "vitest";

import { baselineDistanceKm, loadBarHeightRatio } from "./difficultyLoadBar";

describe("baselineDistanceKm", () => {
  it("一覧の中で最も短い候補の距離（並び順によらない）", () => {
    expect(baselineDistanceKm([{ distance_km: 30 }, { distance_km: 12.5 }, { distance_km: 20 }])).toBe(12.5);
  });

  it("距離が0の候補は基準にしない", () => {
    expect(baselineDistanceKm([{ distance_km: 0 }, { distance_km: 18 }])).toBe(18);
  });

  it("基準にできる候補が無ければnull", () => {
    expect(baselineDistanceKm([])).toBeNull();
    expect(baselineDistanceKm([{ distance_km: 0 }])).toBeNull();
  });
});

describe("loadBarHeightRatio", () => {
  it("基準より長い候補は、距離の比を小数2桁へ丸めた高さ", () => {
    expect(loadBarHeightRatio(15, 10)).toBe(1.5);
    expect(loadBarHeightRatio(12.345, 10)).toBe(1.23);
  });

  it("基準の候補そのものは1.0", () => {
    expect(loadBarHeightRatio(10, 10)).toBe(1);
  });

  it("比が大きい候補は上限で頭打ちになり、それ以上は伸びない", () => {
    const capped = loadBarHeightRatio(100, 10);
    expect(capped).toBeGreaterThan(1);
    expect(loadBarHeightRatio(1000, 10)).toBe(capped);
    expect(loadBarHeightRatio(15, 10)).toBeLessThan(capped);
  });

  it("基準が無ければ1.0（帯は長さだけを表す）", () => {
    expect(loadBarHeightRatio(25, null)).toBe(1);
  });

  it("基準にしなかった距離0の候補も1.0より低くならない", () => {
    expect(loadBarHeightRatio(0, 10)).toBe(1);
  });
});

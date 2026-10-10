// @vitest-environment node
/**
 * `features/route/geoDistance.ts: cumulativeDistancesKm`——座標列（GeoJSONの[経度, 緯度]）の各点までの累積距離（km）。
 *
 * 2点の距離の答えはbackendが出す表（生成物`geo-expectations.json`の`distance_km`）が持つ（testing-frontend.md「パターン11」）。
 * ここでは表を全行通すことと、2点の距離を点の順に足し上げることを見る。
 *
 * ここで見ないもの:
 * - 表の答えが正しいこと → backendのテスト（`domain/geo.py`）
 * - 累積距離から区間の位置・長さを出すこと → `routeSplice.test.ts`・`routeEditDiff.test.ts`
 */
import { describe, expect, it } from "vitest";

import geoExpectations from "@/types/generated/geo-expectations.json";

import { cumulativeDistancesKm } from "./geoDistance";

/** 表の答えは小数6桁へ丸めてあるので、その桁までを比べる。 */
const KM_DIGITS = 5;

function pairKm(from: GeoJSON.Position, to: GeoJSON.Position): number {
  return cumulativeDistancesKm([from, to])[1];
}

describe("cumulativeDistancesKm", () => {
  it("backendが出す表の全行で、2点の距離がbackendと同じになる", () => {
    const rows = geoExpectations.distance_km;
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      const km = pairKm([row.from.longitude, row.from.latitude], [row.to.longitude, row.to.latitude]);
      expect(km, JSON.stringify(row)).toBeCloseTo(row.km, KM_DIGITS);
    }
  });

  it("座標と同じ長さで、先頭は0、各点までは隣どうしの距離を順に足した値", () => {
    const points: GeoJSON.Position[] = [
      [139.7, 35.6],
      [139.71, 35.6],
      [139.71, 35.61],
      [139.7, 35.6],
    ];
    const cumulative = cumulativeDistancesKm(points);
    expect(cumulative).toHaveLength(points.length);
    expect(cumulative[0]).toBe(0);
    for (let i = 1; i < points.length; i += 1) {
      expect(cumulative[i]).toBeCloseTo(cumulative[i - 1] + pairKm(points[i - 1], points[i]), 10);
    }
  });
});

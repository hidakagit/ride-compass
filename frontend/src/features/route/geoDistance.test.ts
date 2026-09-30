// @vitest-environment node
/**
 * `features/route/geoDistance.ts`——座標列（`[経度, 緯度]`の並び）の各点までの累積距離。
 *
 * 2点の距離の答えはbackendが出す表（生成物`geo-expectations.json`の`distance_km`）が持つ（testing.md「パターン11」）。
 * 表の点は緯度と経度が違う値なので、`[経度, 緯度]`の読み違いも表で落ちる。
 *
 * ここで見ないもの:
 * - 表の答えが正しいこと → backendのテスト（`domain/geo.py`）
 * - 累積距離から区間の位置を引くこと → `features/route/routeSplice.test.ts`
 */
import { describe, expect, it } from "vitest";

import geoExpectations from "@/types/generated/geo-expectations.json";
import { cumulativeDistancesKm } from "@/features/route/geoDistance";

type Point = { latitude: number; longitude: number };

function position(point: Point): GeoJSON.Position {
  return [point.longitude, point.latitude];
}

const rows = geoExpectations.distance_km;

describe("cumulativeDistancesKm", () => {
  it("1点だけなら、その点までの距離0だけを返す", () => {
    expect(cumulativeDistancesKm([[139.77, 35.68]])).toEqual([0]);
  });

  it("2点の距離が、backendが出す表の全行でbackendと合う", () => {
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      const [start, end] = cumulativeDistancesKm([position(row.from), position(row.to)]);
      expect(start).toBe(0);
      expect(end, JSON.stringify(row)).toBeCloseTo(row.km, 5);
    }
  });

  it("3点以上では、各点までの区間の距離を足していく", () => {
    const row = rows.find((candidate) => candidate.km > 0);
    expect(row).toBeDefined();
    const { from, to, km } = row!;

    const cumulative = cumulativeDistancesKm([position(from), position(to), position(from)]);

    expect(cumulative).toHaveLength(3);
    expect(cumulative[1]).toBeCloseTo(km, 5);
    expect(cumulative[2]).toBeCloseTo(2 * km, 5);
  });
});

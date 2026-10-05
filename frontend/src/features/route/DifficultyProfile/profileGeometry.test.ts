// @vitest-environment node
/**
 * `features/route/DifficultyProfile/profileGeometry.ts`——道のりの難易度のグラフの形と、グラフ上の距離から地図の地点を引く計算。
 * - `profileColumns`: 区間の長さを積み上げて、区間ごとの柱の始まりと終わりの距離にする
 * - `profileBoxes`: 値のある区間は軸の寄与を指定の順に下から積み（寄与の無い軸は積まない）、値の無い区間は
 *   ルートの総合難易度の高さの1本にする。長さの無い区間は描かない
 * - `columnAtKm`: 距離が入る柱と、その柱の中の割合。範囲の外は端の柱へ寄せ、長さの無い柱は選ばない
 * - `pointAlongSegment`: 区間の道なりの形の上で割合だけ進んだ地点。経度は緯度で縮めて長さを測る。形が無ければ両端を結ぶ直線の上
 *
 * ここで見ないもの:
 * - 長方形を絵にすること・押した位置から距離を出すこと・選んだ地点を区間の選択にすること → `DifficultyProfile.test.tsx`
 */
import { describe, expect, it } from "vitest";

import { makeRouteSegment } from "@/testing/routeFixtures";
import type { RouteSegmentDetail } from "@/types/route";

import { columnAtKm, pointAlongSegment, profileBoxes, profileColumns } from "./profileGeometry";

/** 区間。難易度は、指定しなければ軸の寄与の合計（backendが区間の難易度を寄与へ分けるのと同じ関係）。 */
function segment(overrides: Partial<RouteSegmentDetail> = {}): RouteSegmentDetail {
  const contributions = overrides.axis_contributions ?? {};
  return makeRouteSegment({
    distance_km: 1,
    difficulty: Object.values(contributions).reduce((sum, value) => sum + value, 0),
    end_longitude: 1,
    ...overrides,
  });
}

function line(coordinates: number[][]): RouteSegmentDetail["geometry"] {
  return { type: "LineString", coordinates };
}

describe("profileColumns", () => {
  it("区間の長さを順に積み上げて、柱の始まりと終わりの距離にする", () => {
    const segments = [segment({ distance_km: 0.5 }), segment({ distance_km: 0.25 }), segment({ distance_km: 0.4 })];
    const columns = profileColumns(segments);
    expect(columns.map(({ index, startKm, endKm }) => [index, startKm, endKm])).toEqual([
      [0, 0, 0.5],
      [1, 0.5, 0.75],
      [2, 0.75, 1.15],
    ]);
    expect(columns.map((c) => c.segment)).toEqual(segments);
  });
});

describe("profileBoxes", () => {
  it("値のある区間は、軸の寄与を指定の順に下から積む", () => {
    const columns = profileColumns([
      segment({ distance_km: 2, axis_contributions: { wind: 10, slope: 30 } }),
      segment({ distance_km: 1, axis_contributions: { wind: 5, slope: 15 } }),
    ]);
    const { byAxis } = profileBoxes(columns, ["slope", "wind"], 40);
    expect(byAxis.get("slope")).toEqual([
      { startKm: 0, endKm: 2, bottom: 0, top: 30 },
      { startKm: 2, endKm: 3, bottom: 0, top: 15 },
    ]);
    expect(byAxis.get("wind")).toEqual([
      { startKm: 0, endKm: 2, bottom: 30, top: 40 },
      { startKm: 2, endKm: 3, bottom: 15, top: 20 },
    ]);
  });

  it("寄与の無い軸は積まず、上の軸はその分下がる。指定の順に無い軸は描かない", () => {
    const columns = profileColumns([segment({ axis_contributions: { light: 25, other: 10 } })]);
    const { byAxis } = profileBoxes(columns, ["slope", "light"], 40);
    expect(byAxis.get("slope")).toEqual([]);
    expect(byAxis.get("light")).toEqual([{ startKm: 0, endKm: 1, bottom: 0, top: 25 }]);
  });

  it("値の無い区間は、ルートの総合難易度の高さの1本にする", () => {
    const columns = profileColumns([
      segment({ distance_km: 1, axis_contributions: { wind: 20 } }),
      segment({ distance_km: 0.5, difficulty: null, axis_contributions: { wind: 99 } }),
    ]);
    const { byAxis, missing } = profileBoxes(columns, ["wind"], 35);
    expect(missing).toEqual([{ startKm: 1, endKm: 1.5, bottom: 0, top: 35 }]);
    expect(byAxis.get("wind")).toEqual([{ startKm: 0, endKm: 1, bottom: 0, top: 20 }]);
  });

  it.each([
    ["総合難易度が無い", null],
    ["総合難易度が0", 0],
  ])("%sなら、値の無い区間は描かない", (_label, average) => {
    const columns = profileColumns([segment({ difficulty: null })]);
    expect(profileBoxes(columns, ["wind"], average).missing).toEqual([]);
  });

  it("長さの無い区間は描かない", () => {
    const columns = profileColumns([segment({ distance_km: 0, axis_contributions: { wind: 20 } })]);
    expect(profileBoxes(columns, ["wind"], 35).byAxis.get("wind")).toEqual([]);
  });
});

describe("columnAtKm", () => {
  const columns = profileColumns([
    segment({ distance_km: 1 }),
    segment({ distance_km: 0 }),
    segment({ distance_km: 2 }),
  ]);

  it("距離が入る柱と、柱の中の割合", () => {
    expect(columnAtKm(columns, 0.25)).toEqual({ column: columns[0], fraction: 0.25 });
  });

  it("柱の境目ちょうどは後ろの柱の始まりで、長さの無い柱は選ばない", () => {
    expect(columnAtKm(columns, 1)).toEqual({ column: columns[2], fraction: 0 });
  });

  it("範囲の外は端の柱へ寄せ、割合は0〜1に収める", () => {
    expect(columnAtKm(columns, -0.5)).toEqual({ column: columns[0], fraction: 0 });
    expect(columnAtKm(columns, 10)).toEqual({ column: columns[2], fraction: 1 });
  });

  it("長さのある柱が無ければnull", () => {
    expect(columnAtKm(profileColumns([segment({ distance_km: 0 })]), 0)).toBeNull();
  });
});

describe("pointAlongSegment", () => {
  it("道なりの形の上で、長さの割合だけ進んだ地点", () => {
    const bent = segment({
      geometry: line([
        [0, 0],
        [1, 0],
        [1, 1],
      ]),
    });
    expect(pointAlongSegment(bent, 0.25)).toEqual([0.5, 0]);
    expect(pointAlongSegment(bent, 0.75)[0]).toBeCloseTo(1);
    expect(pointAlongSegment(bent, 0.75)[1]).toBeCloseTo(0.5);
  });

  it("経度方向の長さは緯度で縮めて測る", () => {
    // 北緯60度では経度2度と緯度1度がほぼ同じ長さなので、2つの辺の長さは等しい。
    const bent = segment({
      geometry: line([
        [0, 60],
        [2, 60],
        [2, 61],
      ]),
    });
    const [lng, lat] = pointAlongSegment(bent, 0.5);
    expect(lng).toBeCloseTo(2);
    expect(lat).toBeCloseTo(60);
  });

  it("形が無ければ、区間の始点と終点を結ぶ直線の上", () => {
    const straight = segment({
      geometry: null,
      start_longitude: 139.7,
      start_latitude: 35.6,
      end_longitude: 139.8,
      end_latitude: 35.7,
    });
    const [lng, lat] = pointAlongSegment(straight, 0.5);
    expect(lng).toBeCloseTo(139.75);
    expect(lat).toBeCloseTo(35.65);
  });

  it("長さの無い形は、その地点", () => {
    expect(
      pointAlongSegment(
        segment({
          geometry: line([
            [139.7, 35.6],
            [139.7, 35.6],
          ]),
        }),
        0.5,
      ),
    ).toEqual([139.7, 35.6]);
  });

  it("形の先頭に同じ点が続いても、割合0は始点", () => {
    expect(
      pointAlongSegment(
        segment({
          geometry: line([
            [1, 0],
            [1, 0],
            [2, 0],
          ]),
        }),
        0,
      ),
    ).toEqual([1, 0]);
  });
});

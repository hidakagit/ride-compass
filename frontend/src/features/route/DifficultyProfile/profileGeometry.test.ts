// @vitest-environment node
import { describe, expect, it } from "vitest";

import { columnAtKm, pointAlongSegment, profileBoxes, profileColumns } from "./profileGeometry";

type Segment = Parameters<typeof profileColumns>[0][number];

function segment(overrides: Partial<Segment> & Pick<Segment, "distance_km">): Segment {
  return {
    difficulty: null,
    axis_contributions: {},
    geometry: null,
    start_latitude: 35,
    start_longitude: 139,
    end_latitude: 35,
    end_longitude: 139.01,
    ...overrides,
  };
}

const area = (boxes: readonly { startKm: number; endKm: number; bottom: number; top: number }[]) =>
  boxes.reduce((sum, box) => sum + (box.endKm - box.startKm) * (box.top - box.bottom), 0);

describe("道のりに沿った難易度の形", () => {
  // 負荷は「値のある区間の距離加重平均 × 全長」（backend domain/difficulty.py: difficulty_load）。
  it("塗った面積の合計がルートの負荷に一致する（値の無い区間は平均の高さで数える）", () => {
    const segments = [
      segment({ distance_km: 2, difficulty: 30, axis_contributions: { a: 20, b: 10 } }),
      segment({ distance_km: 1, difficulty: null }),
      segment({ distance_km: 3, difficulty: 60, axis_contributions: { a: 15, b: 45 } }),
    ];
    const average = (30 * 2 + 60 * 3) / 5;
    const load = average * 6;

    const { byAxis, missing } = profileBoxes(profileColumns(segments), ["a", "b"], average);

    const total = [...byAxis.values()].reduce((sum, boxes) => sum + area(boxes), 0) + area(missing);
    expect(total).toBeCloseTo(load);
    // 色ごとの面積がその軸の負荷。
    expect(area(byAxis.get("a") ?? [])).toBeCloseTo(20 * 2 + 15 * 3);
  });

  it("軸は渡した並びの順に下から積み、区間の中で隙間なく重ならない", () => {
    const { byAxis } = profileBoxes(
      profileColumns([segment({ distance_km: 1, difficulty: 30, axis_contributions: { a: 20, b: 10 } })]),
      ["b", "a"],
      30,
    );
    expect(byAxis.get("b")).toEqual([{ startKm: 0, endKm: 1, bottom: 0, top: 10 }]);
    expect(byAxis.get("a")).toEqual([{ startKm: 0, endKm: 1, bottom: 10, top: 30 }]);
  });

  it("区間は長さを積み上げた位置に並び、柱の間に隙間ができない", () => {
    const columns = profileColumns([segment({ distance_km: 0.333 }), segment({ distance_km: 0.667 })]);
    expect(columns[1].startKm).toBe(columns[0].endKm);
    expect(columns[1].endKm).toBeCloseTo(1);
  });
});

describe("グラフ上の距離から地点を引く", () => {
  const columns = profileColumns([
    segment({ distance_km: 1 }),
    segment({ distance_km: 0 }),
    segment({ distance_km: 2 }),
  ]);

  it("距離が入っている区間と、その中の割合を返す", () => {
    expect(columnAtKm(columns, 0.5)).toMatchObject({ column: { index: 0 }, fraction: 0.5 });
    expect(columnAtKm(columns, 2)).toMatchObject({ column: { index: 2 }, fraction: 0.5 });
  });

  it("区間の境目は後ろの区間に入り、長さ0の区間は選ばない", () => {
    expect(columnAtKm(columns, 1)).toMatchObject({ column: { index: 2 }, fraction: 0 });
  });

  it("範囲の外は端の区間へ寄せる", () => {
    expect(columnAtKm(columns, -1)).toMatchObject({ column: { index: 0 }, fraction: 0 });
    expect(columnAtKm(columns, 10)).toMatchObject({ column: { index: 2 }, fraction: 1 });
    expect(columnAtKm([], 1)).toBeNull();
  });

  it("地点は区間の道なりの形の上を、長さの割合で進む", () => {
    // 折れ線の1本目が2本目の3倍長い。半分進んだ地点は1本目の中（2/3の位置）にある。
    const bent = segment({
      distance_km: 1,
      geometry: {
        type: "LineString",
        coordinates: [
          [0, 0],
          [0.003, 0],
          [0.003, 0.001],
        ],
      },
      start_latitude: 0,
      start_longitude: 0,
      end_latitude: 0.001,
      end_longitude: 0.003,
    });
    const [lng, lat] = pointAlongSegment(bent, 0.5);
    expect(lng).toBeCloseTo(0.002, 6);
    expect(lat).toBeCloseTo(0, 6);
  });

  it("形の無い区間は、始点と終点を結ぶ直線の上を進む", () => {
    const [lng, lat] = pointAlongSegment(segment({ distance_km: 1 }), 0.25);
    expect(lng).toBeCloseTo(139.0025, 6);
    expect(lat).toBeCloseTo(35, 6);
  });
});

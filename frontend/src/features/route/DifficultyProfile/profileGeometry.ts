// 道のりに沿った難易度のグラフの形と、グラフ上の距離から地図の場所を引く計算。
//
// 横が始点からの距離、縦が区間ごとの難易度（0〜100）。区間はbackendがEdgeを約500mのビンへ畳んだもの
// （`domain/route.py: aggregate_segments_into_bins`）で、区間の中では値が一定なので、形は区間ごとの階段になる。
// **塗った面積がルートの負荷とほぼ一致する**ように、値の無い区間はルートの平均の高さで描く——負荷は
// 「値のある区間の距離加重平均 × 値の無い区間も含めた全長」（backend `domain/difficulty.py: difficulty_load`）で、
// 値の無い区間を平均として数えているため。一致が「ほぼ」なのは、ビンの中で値の無いEdgeがそのビンの平均で数えられるため。

import type { RouteSegmentDetail } from "@/types/route";

type ProfileSegment = Pick<
  RouteSegmentDetail,
  | "distance_km"
  | "difficulty"
  | "axis_contributions"
  | "geometry"
  | "start_latitude"
  | "start_longitude"
  | "end_latitude"
  | "end_longitude"
>;

/** 区間1本ぶんの柱。`startKm`は区間の長さを積み上げた値（丸めた累積距離は使わない——丸めの分だけ柱の間に隙間ができる）。 */
export type ProfileColumn<S extends ProfileSegment = ProfileSegment> = {
  readonly segment: S;
  readonly index: number;
  readonly startKm: number;
  readonly endKm: number;
};

export function profileColumns<S extends ProfileSegment>(segments: readonly S[]): ProfileColumn<S>[] {
  const columns: ProfileColumn<S>[] = [];
  let km = 0;
  segments.forEach((segment, index) => {
    const length = Math.max(0, segment.distance_km);
    columns.push({ segment, index, startKm: km, endKm: km + length });
    km += length;
  });
  return columns;
}

/** 塗る長方形1つ（距離と難易度の座標）。 */
export type ProfileBox = {
  readonly startKm: number;
  readonly endKm: number;
  readonly bottom: number;
  readonly top: number;
};

/**
 * 軸ごとに積み上げた長方形と、値の無い区間の長方形。軸は`axisOrder`の順に下から積む（区間の軸別の寄与を合計すると
 * その区間の難易度になる）。`averageDifficulty`はルートの総合難易度で、値の無い区間の高さに使う。
 */
export function profileBoxes(
  columns: readonly ProfileColumn[],
  axisOrder: readonly string[],
  averageDifficulty: number | null,
): { byAxis: Map<string, ProfileBox[]>; missing: ProfileBox[] } {
  const byAxis = new Map<string, ProfileBox[]>(axisOrder.map((axisId) => [axisId, []]));
  const missing: ProfileBox[] = [];
  for (const { segment, startKm, endKm } of columns) {
    if (endKm <= startKm) continue;
    if (segment.difficulty === null || segment.difficulty === undefined) {
      if (averageDifficulty !== null && averageDifficulty > 0) {
        missing.push({ startKm, endKm, bottom: 0, top: averageDifficulty });
      }
      continue;
    }
    let bottom = 0;
    for (const axisId of axisOrder) {
      const value = segment.axis_contributions[axisId] ?? 0;
      if (value <= 0) continue;
      byAxis.get(axisId)?.push({ startKm, endKm, bottom, top: bottom + value });
      bottom += value;
    }
  }
  return { byAxis, missing };
}

/** 距離`km`が入っている柱と、その区間の中の割合（0〜1）。範囲の外は端の区間へ寄せる。区間が無ければnull。 */
export function columnAtKm<S extends ProfileSegment>(
  columns: readonly ProfileColumn<S>[],
  km: number,
): { column: ProfileColumn<S>; fraction: number } | null {
  const usable = columns.filter((column) => column.endKm > column.startKm);
  if (usable.length === 0) return null;
  let low = 0;
  let high = usable.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (km < usable[mid].endKm) high = mid;
    else low = mid + 1;
  }
  const column = usable[low];
  const fraction = (km - column.startKm) / (column.endKm - column.startKm);
  return { column, fraction: Math.min(1, Math.max(0, fraction)) };
}

/** 区間の道なりの形の上で、始点から割合`fraction`だけ進んだ点（[経度, 緯度]）。形が無ければ始点と終点を結ぶ直線の上。 */
export function pointAlongSegment(segment: ProfileSegment, fraction: number): [number, number] {
  const geometry = segment.geometry as { type?: string; coordinates?: [number, number][] } | null | undefined;
  const coordinates =
    geometry?.type === "LineString" && Array.isArray(geometry.coordinates) && geometry.coordinates.length >= 2
      ? geometry.coordinates
      : ([
          [segment.start_longitude, segment.start_latitude],
          [segment.end_longitude, segment.end_latitude],
        ] as [number, number][]);
  // 区間は短いので、緯度で経度方向を縮めた平面の距離で足りる（割合を決めるだけで、長さそのものは使わない）。
  const scale = Math.cos((coordinates[0][1] * Math.PI) / 180);
  const lengths = coordinates.slice(1).map(([lng, lat], i) => {
    const [prevLng, prevLat] = coordinates[i];
    return Math.hypot((lng - prevLng) * scale, lat - prevLat);
  });
  const total = lengths.reduce((sum, length) => sum + length, 0);
  if (total === 0) return coordinates[0];
  let remaining = Math.min(1, Math.max(0, fraction)) * total;
  for (let i = 0; i < lengths.length; i++) {
    if (remaining <= lengths[i] || i === lengths.length - 1) {
      const t = lengths[i] === 0 ? 0 : Math.min(1, remaining / lengths[i]);
      const [fromLng, fromLat] = coordinates[i];
      const [toLng, toLat] = coordinates[i + 1];
      return [fromLng + (toLng - fromLng) * t, fromLat + (toLat - fromLat) * t];
    }
    remaining -= lengths[i];
  }
  return coordinates[coordinates.length - 1];
}

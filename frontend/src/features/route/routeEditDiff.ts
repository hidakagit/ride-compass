/**
 * 編集で作ったルートが、元にしたルートから何を変えたか。
 *
 * 変えた区間は、編集の手順（適用した乗り換えの列）からではなく**できた2本のEdge id列の差**から求める
 * ——乗り換えの範囲はそれぞれ適用した時点の経路に対する位置で、続けて当てた乗り換えを元の位置へ戻す
 * には手順の全部が要る。差なら、隣り合った乗り換えが1つの区間にまとまることも含めて、利用者が
 * 地図で見比べる形そのものになる。
 */
import { cumulativeDistancesKm } from "@/features/route/geoDistance";
import { pairedStretches } from "@/features/route/routeSplice";
import type { RouteCandidate } from "@/types/route";

/** 変えた区間1つ。位置は元のルートの始点からの距離。 */
interface ChangedStretch {
  startKm: number;
  endKm: number;
  /** 変えた後の区間の長さ − 元の区間の長さ。 */
  lengthDiffKm: number;
}

/** 元との差（編集後 − 元）。値を持たない側があればnull。 */
export interface EditDifference {
  distanceKm: number;
  durationSeconds: number | null;
  difficulty: number | null;
  load: number | null;
  /** 起点に近い順。 */
  stretches: ChangedStretch[];
}

type Shape = Pick<RouteCandidate, "edge_ids" | "edge_point_offsets" | "geometry">;

/** `edge_ids`の`index`番目のEdgeの始点までの距離（km）。 */
function kmAtEdge(shape: Shape, cumulativeKm: readonly number[], index: number): number {
  return cumulativeKm[shape.edge_point_offsets[index]];
}

function diffOf(after: number | null | undefined, before: number | null | undefined): number | null {
  return after === null || after === undefined || before === null || before === undefined ? null : after - before;
}

export function editDifference(origin: RouteCandidate, edited: RouteCandidate): EditDifference {
  const pairs = pairedStretches(origin.edge_ids, edited.edge_ids);
  const originKm = cumulativeDistancesKm(origin.geometry.coordinates);
  const editedKm = cumulativeDistancesKm(edited.geometry.coordinates);
  const stretches = pairs.map((pair) => {
    const startKm = kmAtEdge(origin, originKm, pair.displayed.start);
    const endKm = kmAtEdge(origin, originKm, pair.displayed.end);
    const editedStartKm = kmAtEdge(edited, editedKm, pair.target.start);
    const editedEndKm = kmAtEdge(edited, editedKm, pair.target.end);
    return { startKm, endKm, lengthDiffKm: editedEndKm - editedStartKm - (endKm - startKm) };
  });
  return {
    distanceKm: edited.distance_km - origin.distance_km,
    durationSeconds: diffOf(edited.estimated_duration_seconds, origin.estimated_duration_seconds),
    difficulty: diffOf(edited.overall_difficulty?.average, origin.overall_difficulty?.average),
    load: diffOf(edited.overall_difficulty?.load, origin.overall_difficulty?.load),
    stretches,
  };
}

/** 表示する桁で丸めた差。色を変えるかどうかも**この値**で決める——生の差で判断すると、
 * 画面には「±0」と出ているのに色だけ増減を主張する。 */
export function roundToDigits(value: number, digits: number): number {
  return Number(value.toFixed(digits));
}

/** 差の表記（例: `+0.4`・`−2`・`±0`）。 */
export function formatDelta(value: number, digits: number): string {
  const rounded = roundToDigits(value, digits);
  if (rounded === 0) return "±0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(digits)}`;
}

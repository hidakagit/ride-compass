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
import { DIFFICULTY_DECIMALS, LOAD_DECIMALS } from "@/lib/mapDisplay/valueScale";
import type { RouteCandidate } from "@/types/route";

/** 変えた区間1つ。位置は元のルートの始点からの距離。 */
interface ChangedStretch {
  startKm: number;
  endKm: number;
  /** 変えた後の区間の長さ − 元の区間の長さ。 */
  lengthDiffKm: number;
}

/** 編集の前後で見比べる指標の1つ。`value`は表示の単位（所要は分）で、値が無ければnull。 */
interface EditMetric {
  label: string;
  /** 表示の桁。差を丸めて色を決めるのも同じ桁。 */
  digits: number;
  unit: string;
  value: (route: RouteCandidate) => number | null;
}

/** 見比べる指標（ルート結果と同じ項目）。編集面とできたルートの「元との違い」がこの1つの表を読む。 */
const EDIT_METRICS: readonly EditMetric[] = [
  { label: "距離", digits: 1, unit: "km", value: (route) => route.distance_km },
  {
    label: "所要",
    digits: 0,
    unit: "分",
    value: (route) => (route.estimated_duration_seconds === null ? null : route.estimated_duration_seconds / 60),
  },
  {
    label: "総合難易度",
    digits: DIFFICULTY_DECIMALS,
    unit: "",
    value: (route) => route.overall_difficulty?.average ?? null,
  },
  { label: "負荷", digits: LOAD_DECIMALS, unit: "", value: (route) => route.overall_difficulty?.load ?? null },
];

/** 指標1つの元・編集後と差（編集後 − 元）。値を持たない側があれば差はnull。 */
export interface MetricDifference {
  label: string;
  digits: number;
  unit: string;
  base: number | null;
  after: number | null;
  delta: number | null;
}

/** 元との差。 */
export interface EditDifference {
  metrics: MetricDifference[];
  /** 起点に近い順。 */
  stretches: ChangedStretch[];
}

type Shape = Pick<RouteCandidate, "edge_ids" | "edge_point_offsets" | "geometry">;

/** `edge_ids`の`index`番目のEdgeの始点までの距離（km）。 */
function kmAtEdge(shape: Shape, cumulativeKm: readonly number[], index: number): number {
  return cumulativeKm[shape.edge_point_offsets[index]];
}

/** 指標ごとの元・編集後と差。編集後がまだ無ければ（評価する前）元の値だけを持つ。 */
export function metricDifferences(origin: RouteCandidate, edited: RouteCandidate | null): MetricDifference[] {
  return EDIT_METRICS.map(({ value, ...metric }) => {
    const base = value(origin);
    const after = edited === null ? null : value(edited);
    return { ...metric, base, after, delta: base === null || after === null ? null : after - base };
  });
}

/** 指標の値の表記（例: `12.3km`・`38分`・`42`）。 */
export function formatMetric(metric: Pick<MetricDifference, "digits" | "unit">, value: number): string {
  return `${value.toFixed(metric.digits)}${metric.unit}`;
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
  return { metrics: metricDifferences(origin, edited), stretches };
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

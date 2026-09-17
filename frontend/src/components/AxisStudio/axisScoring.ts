/** 材料の生値を折れ点の横軸(x)の値へ変換する。backend: domain/axis_definitions.py:
 * evaluate_axis_scalarの`total = value * weight`→`abs()`（preprocess="abs"の場合）と
 * 同じ変換（`terms`が1件のbreakpoint_linear軸限定、複数termの合計は対応しない）。 */
export function toBreakpointX(value: number, weight: number, preprocess: "identity" | "abs"): number {
  const total = value * weight;
  return preprocess === "abs" ? Math.abs(total) : total;
}

// 地図の式（色・線種・凡例の行の述語）を、MapLibreと同じ評価器で1本の地物に当てる。式の形ではなく、その地物が
// どう描かれるか・どの行に当てはまるかを見るために使う。ズームは式が読まない値で固定する。
import { createExpression, featureFilter, type FilterSpecification } from "@maplibre/maplibre-gl-style-spec";

const GLOBALS = { zoom: 14 } as never;

/** 式を、地物のプロパティへ当てた値。式として読めなければ、評価器の指摘を並べて投げる。 */
export function evaluateExpression(expression: unknown, properties: Record<string, unknown>): unknown {
  const compiled = createExpression(expression, "paint");
  if (compiled.result !== "success") {
    throw new Error(compiled.value.map((error) => `${error.key}: ${error.message}`).join("; "));
  }
  return compiled.value.evaluateWithoutErrorHandling(GLOBALS, { type: 2, properties } as never, {});
}

/** 絞り（凡例の行の述語・レイヤーの`filter`）が、そのプロパティの地物に当てはまるか。`geometry`は地物の形
 * （MapLibreの番号で1が点・2が線・3が面。絞りが`geometry-type`を読むときに効く）。 */
export function matchesFilter(filter: unknown, properties: Record<string, unknown>, geometry: 1 | 2 | 3 = 2): boolean {
  return featureFilter(filter as FilterSpecification, "filter").filter(GLOBALS, {
    type: geometry,
    properties,
  } as never);
}

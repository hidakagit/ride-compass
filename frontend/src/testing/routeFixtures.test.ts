// @vitest-environment node
/**
 * `testing/routeFixtures.ts: routeThrough`——地点を順に通る経路の形を、backendの契約（`backend/app/domain/route.py:
 * RouteCandidate`の`edge_point_offsets`・`node_ids`）どおりに組む。契約からずれると、区間ごとに形を切り出す
 * 実装のテストが、本番で来ない形の上で緑になる。
 *
 * ここで見ないもの: `make*`（型を満たす値を並べるだけ）
 */
import { describe, expect, it } from "vitest";

import { routeThrough } from "./routeFixtures";

const PLACES = { a: [139.7, 35.6], b: [139.8, 35.6], c: [139.8, 35.7] } as const;

describe("routeThrough", () => {
  it("Edge iの形は、座標の列のoffsets[i]からoffsets[i+1]までで、Node iからNode i+1へ向かう", () => {
    const names = ["a", "b", "c"] as const;
    const { edge_ids, edge_point_offsets, node_ids, geometry } = routeThrough(PLACES, names);

    expect(edge_point_offsets).toHaveLength(edge_ids.length + 1);
    expect(node_ids).toEqual(names);
    expect(edge_point_offsets.at(-1)).toBe(geometry.coordinates.length - 1);
    edge_ids.forEach((_, i) => {
      const shape = geometry.coordinates.slice(edge_point_offsets[i], edge_point_offsets[i + 1] + 1);
      expect(shape.length).toBeGreaterThan(1);
      expect([shape[0], shape.at(-1)]).toEqual([PLACES[names[i]], PLACES[names[i + 1]]]);
    });
  });
});

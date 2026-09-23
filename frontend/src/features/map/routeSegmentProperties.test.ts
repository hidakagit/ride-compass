// @vitest-environment node
import { describe, expect, it } from "vitest";

import openapi from "@/types/generated/openapi.json";
import type { RouteSegmentDetail } from "@/types/route";

import { restoreRouteSegmentProperties, type SerializedRouteSegmentProperties } from "./routeSegmentProperties";

describe("restoreRouteSegmentProperties（押された区間の値を戻す）", () => {
  it("契約でオブジェクト値のフィールドは、どれもJSON文字列から元のオブジェクトへ戻る", () => {
    const schema = openapi.components.schemas.RouteSegmentDetail.properties as Record<string, { type?: string }>;
    const objectFields = Object.entries(schema)
      .filter(([name, field]) => name !== "geometry" && field.type === "object")
      .map(([name]) => name);
    expect(objectFields).not.toHaveLength(0);

    const segment: Omit<RouteSegmentDetail, "geometry"> = {
      start_latitude: 35,
      start_longitude: 139,
      end_latitude: 35.1,
      end_longitude: 139.1,
      cumulative_distance_km: 1,
      distance_km: 1,
      estimated_arrival_time: "2026-09-24T09:00:00+09:00",
      difficulty: 40,
      axis_difficulties: { a: 1 },
      axis_contributions: { a: 2 },
      material_values: { m: 3 },
      axis_raw_values: { a: 4 },
    };
    // 地図が地物のプロパティを内部表現へ移すときと同じく、オブジェクトだけを文字列にする
    const serialized = Object.fromEntries(
      Object.entries(segment).map(([key, value]) => [key, objectFields.includes(key) ? JSON.stringify(value) : value]),
    ) as unknown as SerializedRouteSegmentProperties;
    expect(restoreRouteSegmentProperties(serialized)).toEqual(segment);
  });
});

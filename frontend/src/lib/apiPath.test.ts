// @vitest-environment node
/**
 * `lib/apiPath.ts`——backendが宣言したパスの`{名前}`を値で埋める。
 *
 * パスはbackendの契約（生成物`paths`のキー）しか受け付けないので、契約にあるパスを入力に使う。
 *
 * ここで見ないもの:
 * - 埋めたパスにオリジンを付けて地図ライブラリへ渡すこと → 使う側（`features/map/layers/jmaDelivery.test.ts`等）
 */
import { describe, expect, it } from "vitest";

import { apiPath } from "@/lib/apiPath";

describe("apiPath", () => {
  it("渡した名前を値で埋め、数値は文字列にする", () => {
    expect(
      apiPath("/api/region/dynamic-way-values/{axis_id}/{z}/{x}/{y}", { axis_id: "wind", z: 14, x: 1, y: 2 }),
    ).toBe("/api/region/dynamic-way-values/wind/14/1/2");
  });

  it("渡さなかった名前は`{名前}`のまま残す（タイルの座標は地図ライブラリが埋める）", () => {
    expect(apiPath("/api/region/road-surface-tiles/{z}/{x}/{y}.pbf")).toBe(
      "/api/region/road-surface-tiles/{z}/{x}/{y}.pbf",
    );
  });

  it("値は区切りの`/`を含めてそのまま埋める", () => {
    expect(apiPath("/api/basemap/{path}", { path: "styles/liberty" })).toBe("/api/basemap/styles/liberty");
  });
});

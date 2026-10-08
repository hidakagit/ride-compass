// @vitest-environment node
/** 重なった点の絵を間引くレイヤーが、源泉の宣言の順（先に並ぶ行・同じ行の中では割合の大きい点）で点を残すこと。
 *
 * ここで見ないもの:
 * - 凡例の見本と地図の点の色・絵の一致、凡例の行ごとの絞り込み → `scene/legends.test.ts`
 * - 地図が重なった絵を実際に省くこと（MapLibreの置き方そのもの）
 */
import { describe, expect, it } from "vitest";

import { evaluateExpression as evaluate } from "@/testing/mapExpressions";

import { POINT_LAYERS, pointGroup } from "./points";

const TILES = {
  urls: {
    poi: ["https://example.test/poi/{z}/{x}/{y}"],
    accident: ["https://example.test/accident/{z}/{x}/{y}"],
    stop_place: ["https://example.test/stop_place/{z}/{x}/{y}"],
  },
  minZoom: 10,
  maxZoom: 14,
};

function layoutOf(role: string): Record<string, unknown> {
  const layer = pointGroup.build({ tiles: TILES, visible: {}, hiddenKeys: {} }).layers.find((l) => l.role === role);
  if (layer === undefined) throw new Error(`${role} の層が無い`);
  return layer.layout as Record<string, unknown>;
}

const THINNED = POINT_LAYERS.flatMap((layer) =>
  layer.point_thinning === null ? [] : [[layer.attr_id, layer] as const],
);

describe("重なった点の間引き", () => {
  it("間引く点のレイヤーがある", () => {
    expect(THINNED.length).toBeGreaterThan(0);
  });

  it.each(THINNED)("%s は、先に並ぶ行の点を、同じ行の中では割合の大きい点を先に残す", (attrId, layer) => {
    const thinning = layer.point_thinning!;
    const axis = layer.display_axes[0];
    const layout = layoutOf(attrId);
    expect(layout["icon-allow-overlap"]).toBe(false);
    expect(layout["icon-ignore-placement"]).toBe(false);

    // 鍵の小さい点ほど先に置かれ、重なったほかの点を退ける。
    const sortKey = (rowKey: string, ratio: number | undefined) => {
      const value = axis.categories.find((category) => category.key === rowKey)!.values[0];
      return evaluate(layout["symbol-sort-key"], {
        [axis.property]: value,
        ...(ratio === undefined ? {} : { [thinning.ratio_property]: ratio }),
      }) as number;
    };
    const keys = thinning.rows.flatMap((rowKey) => [
      sortKey(rowKey, 1),
      sortKey(rowKey, 0.5),
      sortKey(rowKey, undefined),
    ]);
    expect(keys).toEqual([...keys].sort((a, b) => a - b));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("間引かない絵の点は、重なっても全部描く", () => {
    const unthinned = POINT_LAYERS.filter(
      (layer) => layer.point_thinning === null && layer.display_axes[0].categories.some((c) => "glyph" in c),
    );
    expect(unthinned.length).toBeGreaterThan(0);
    for (const layer of unthinned) {
      expect(layoutOf(layer.attr_id)).toMatchObject({ "icon-allow-overlap": true, "icon-ignore-placement": true });
    }
  });
});

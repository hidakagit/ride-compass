// @vitest-environment node
/**
 * `lib/secondaryAxes.ts`——地図のチップに出す軸の一覧を、軸カタログから作る。
 *
 * 軸は`testing/catalogAxes.ts`の雛形で組む（実際の公開軸を入力に使わない）。
 *
 * ここで見ないもの:
 * - 軸の共通の項目の移し方 → `lib/catalogAxis.test.ts`（ここでは移った印に軸idと略名だけを見る）
 * - 専用レイヤーのidの形と、そのレイヤーを地図へ足すこと → `lib/mapDisplay/axisLayers.test.ts`
 * - チップの描き方（レイヤーの無い軸を薄く出す等） → チップの部品のテスト
 */
import { describe, expect, it } from "vitest";

import { catalogEntry, rampEntry } from "@/testing/catalogAxes";
import { secondaryAxesFromCatalogAxes } from "@/lib/secondaryAxes";

describe("secondaryAxesFromCatalogAxes", () => {
  it("地図のアイコンを出す軸だけを、カタログの並び順のまま返す", () => {
    const axes = secondaryAxesFromCatalogAxes([
      catalogEntry({ axis_id: "axis_c", show_map_icon: true }),
      catalogEntry({ axis_id: "axis_hidden", show_map_icon: false }),
      catalogEntry({ axis_id: "axis_a", show_map_icon: true }),
    ]);

    expect(axes.map((axis) => axis.axisId)).toEqual(["axis_c", "axis_a"]);
  });

  it("軸の共通の項目を持つ", () => {
    const [axis] = secondaryAxesFromCatalogAxes([
      catalogEntry({ axis_id: "axis_a", label: "軸Aの名前", chip_label: "軸A", show_map_icon: true }),
    ]);

    expect(axis).toMatchObject({ axisId: "axis_a", chipLabel: "軸A" });
  });

  it("ramp表示の軸は軸ごとの専用レイヤーを持ち、それ以外の軸は持たない", () => {
    const axes = secondaryAxesFromCatalogAxes([
      rampEntry("ramp_a", [1, 2], { show_map_icon: true }),
      rampEntry("ramp_b", [1, 2], { show_map_icon: true }),
      catalogEntry({ axis_id: "plain_a", show_map_icon: true }),
    ]);
    const [rampA, rampB, plain] = axes;

    expect(rampA.layerId).toBeDefined();
    expect(rampB.layerId).toBeDefined();
    expect(rampA.layerId).not.toBe(rampB.layerId);
    expect(plain.layerId).toBeUndefined();
  });
});

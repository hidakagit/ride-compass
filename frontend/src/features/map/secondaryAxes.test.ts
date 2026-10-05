// @vitest-environment node
/**
 * `features/map/secondaryAxes.ts`——地図のチップに出す軸の一覧を、軸カタログから作る。
 *
 * 軸は`testing/catalogAxes.ts`の雛形で組む（実際の公開軸を入力に使わない）。
 *
 * ここで見ないもの:
 * - 軸の共通の項目の移し方 → `lib/catalogAxis.test.ts`（ここでは移った印に軸idだけを見る）
 * - 専用レイヤーのidの形と、そのレイヤーを地図へ足すこと → `lib/mapDisplay/axisLayers.test.ts`
 * - チップの描き方（レイヤーの無い軸を薄く出す等） → チップの部品のテスト
 */
import { describe, expect, it } from "vitest";

import { catalogEntry, rampEntry } from "@/testing/catalogAxes";
import { secondaryAxesFromCatalogAxes } from "@/features/map/secondaryAxes";

describe("secondaryAxesFromCatalogAxes", () => {
  it("地図のアイコンを出す軸だけを、カタログの並び順のまま返す", () => {
    const axes = secondaryAxesFromCatalogAxes([
      catalogEntry({ axis_id: "axis_c", show_map_icon: true }),
      catalogEntry({ axis_id: "axis_hidden", show_map_icon: false }),
      catalogEntry({ axis_id: "axis_a", show_map_icon: true }),
    ]);

    expect(axes.map((axis) => axis.axisId)).toEqual(["axis_c", "axis_a"]);
  });

  it("ramp表示の軸は専用レイヤーを持ち、それ以外の軸は持たない", () => {
    const axes = secondaryAxesFromCatalogAxes([
      rampEntry("ramp_a", [1, 2], { show_map_icon: true }),
      catalogEntry({ axis_id: "plain_a", show_map_icon: true }),
    ]);
    const [ramp, plain] = axes;

    expect(ramp.layerId).toBeDefined();
    expect(plain.layerId).toBeUndefined();
  });
});

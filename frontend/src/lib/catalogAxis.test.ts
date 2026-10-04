// @vitest-environment node
/**
 * `lib/catalogAxis.ts`——軸カタログの1行を、画面が読む形（`CatalogAxis`）へ移す。
 *
 * 移し方のうち判断を持つのは、略名が無い軸の略名を名前で補うことだけで、それを見る。軸は`testing/catalogAxes.ts`の
 * 雛形で組む（実際の公開軸を入力に使わない）。
 *
 * ここで見ないもの:
 * - 項目をそのまま移すこと（判断が無い）→ 移した項目を描く部品（`components/AxisContributionBar`等）
 * - 移した項目を用途ごとに足した型（地図のチップ・ramp軸・専用配信の軸）→ `features/map/secondaryAxes.test.ts`・
 *   `lib/mapDisplay/axisLayers.test.ts`
 */
import { describe, expect, it } from "vitest";

import { catalogEntry } from "@/testing/catalogAxes";
import { catalogAxisFromEntry } from "@/lib/catalogAxis";

describe("catalogAxisFromEntry", () => {
  it.each([
    ["略名があれば、略名", "軸A", "軸A"],
    ["略名が無ければ、名前", null, "軸Aの名前"],
  ])("狭い幅で並べる名前は、%s", (_scene, chipLabel, expected) => {
    const axis = catalogAxisFromEntry(catalogEntry({ axis_id: "axis_a", label: "軸Aの名前", chip_label: chipLabel }));

    expect(axis.chipLabel).toBe(expected);
  });
});

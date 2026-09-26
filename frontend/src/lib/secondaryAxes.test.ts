// @vitest-environment node
/**
 * `secondaryAxes.ts`——軸カタログの軸から、地図のチップ・地図の見え方パネルへ出す軸の一覧を作ること。
 * 一覧から外すのは`show_map_icon`だけで、ramp軸だけが専用のレイヤーを持つ。軸の共通の項目（略名・単位等）の移し方は
 * `catalogAxis.test.ts`が見る。
 *
 * 軸は架空のもの（`mapDisplay/__fixtures__/catalogAxes.ts`）。
 */
import { describe, expect, it } from "vitest";

import { catalogEntry } from "@/lib/mapDisplay/__fixtures__/catalogAxes";
import { axisMapLayerId } from "@/lib/mapDisplay/axisLayers";

import { secondaryAxesFromCatalogAxes } from "./secondaryAxes";

/** 地図のアイコンを出す軸（一覧に残る側）。 */
const shown: typeof catalogEntry = (overrides = {}) => catalogEntry({ show_map_icon: true, ...overrides });

describe("secondaryAxesFromCatalogAxes", () => {
  it("地図のアイコンを出さない軸だけを外し、カタログの並びのまま出す", () => {
    const axes = secondaryAxesFromCatalogAxes([
      shown({ axis_id: "b" }),
      catalogEntry({ axis_id: "hidden", show_map_icon: false }),
      shown({ axis_id: "a" }),
    ]);
    expect(axes.map((axis) => axis.axisId)).toEqual(["b", "a"]);
  });

  it("地図の表示がrampの軸だけが専用のレイヤーを持つ", () => {
    const [ramp, none] = secondaryAxesFromCatalogAxes([
      shown({ axis_id: "ramp", display: { kind: "ramp" } }),
      shown({ axis_id: "none" }),
    ]);
    expect(ramp.layerId).toBe(axisMapLayerId("ramp"));
    expect(none.layerId).toBeUndefined();
  });
});

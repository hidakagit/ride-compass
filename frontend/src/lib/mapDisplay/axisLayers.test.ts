// @vitest-environment node
/**
 * `lib/mapDisplay/axisLayers.ts`——軸カタログの行を、地図が読む形（ramp軸・専用配信の軸・軸の名前の辞書）へ移すこと。
 * 入口は`rampAxesFromCatalogAxes`・`dedicatedWayValueAxesFromCatalogAxes`・`axisLabelsFromCatalogAxes`で、確かめるのは
 * 戻り値のうち地図の表示の項目。軸は`testing/catalogAxes.ts`の雛形で組む（実際の公開軸を使わない）。
 *
 * ここで見ないもの:
 * - 名前・単位など軸に共通の項目を行から移すこと（`lib/catalogAxis.ts`）→ 判断が無く、移した項目を描く部品
 *   （`components/AxisContributionBar`等）が通す
 * - 表示の宣言の項目（段の境界・凡例の目盛り・体感ラベル・タイルの入力）をそのまま移すこと → 移した軸で道を塗る式と
 *   凡例（`features/map/scene/groups/axisLines.test.ts`の backend の表・`features/map/view/lens.test.ts`）が通す
 * - 地図のレイヤーの鍵（`axisMapLayerId`）→ 文字列の組み立てだけで、レイヤーの登録と可視の切り替えのテストが通す
 */
import { describe, expect, it } from "vitest";

import { catalogEntry, dedicatedEntry, rampEntry, tileInput } from "@/testing/catalogAxes";

import { axisLabelsFromCatalogAxes, dedicatedWayValueAxesFromCatalogAxes, rampAxesFromCatalogAxes } from "./axisLayers";

describe("rampAxesFromCatalogAxes", () => {
  it("地図の表示がrampの軸だけを、カタログの順に残す", () => {
    const axes = [
      rampEntry("ramp_b", [1]),
      catalogEntry({ axis_id: "not_on_map" }),
      dedicatedEntry("dedicated", [1]),
      rampEntry("ramp_a", [1]),
    ];

    expect(rampAxesFromCatalogAxes(axes, {}).map((axis) => axis.axisId)).toEqual(["ramp_b", "ramp_a"]);
  });

  it("実行時の係数が要る入力は、届いた係数を重みへ掛け、届いていなければ寄与0で塗らず「不明」の印を付ける", () => {
    const entry = rampEntry("a", [1], {
      map_paint: {
        tiles: {
          kind: "ramp",
          thresholds: [1],
          tile_inputs: [
            tileInput({ property: "scaled", weight: 2, needs_runtime_scale: true }),
            tileInput({ property: "unscaled", weight: 2, needs_runtime_scale: true }),
            tileInput({ property: "plain", weight: 2 }),
          ],
        },
      },
    });

    const inputs = rampAxesFromCatalogAxes([entry], { scaled: 0.25, plain: 10 })[0].tileInputs;

    expect(inputs.map(({ property, weight, scaleMissing }) => ({ property, weight, scaleMissing }))).toEqual([
      { property: "scaled", weight: 0.5, scaleMissing: undefined },
      { property: "unscaled", weight: 0, scaleMissing: true },
      { property: "plain", weight: 2, scaleMissing: undefined },
    ]);
  });
});

describe("dedicatedWayValueAxesFromCatalogAxes", () => {
  it("専用配信を持つ軸だけを、カタログの順に残す", () => {
    const axes = [dedicatedEntry("d_b", [1]), rampEntry("ramp", [1]), dedicatedEntry("d_a", [1])];

    expect(dedicatedWayValueAxesFromCatalogAxes(axes).map((axis) => axis.axisId)).toEqual(["d_b", "d_a"]);
  });

  it("配信に添える入力（時刻・方位・速度）の要否を、軸ごとにカタログの条件の名前から移す", () => {
    const [timeOnly, bearingAndSpeed] = dedicatedWayValueAxesFromCatalogAxes([
      dedicatedEntry("time_only", [1], { dynamic_way_value_conditions: ["at"] }),
      dedicatedEntry("bearing_speed", [1], { dynamic_way_value_conditions: ["bearing_deg", "speed_kmh"] }),
    ]);

    expect(timeOnly).toMatchObject({ needsTime: true, needsBearing: false, needsSpeed: false });
    expect(bearingAndSpeed).toMatchObject({ needsTime: false, needsBearing: true, needsSpeed: true });
  });
});

describe("axisLabelsFromCatalogAxes", () => {
  it("地図に出ない軸も含めた全軸を、地図の表示名ではなく軸の名前で引ける", () => {
    const labels = axisLabelsFromCatalogAxes([
      rampEntry("on_map", [1], { label: "地図に出る軸" }),
      catalogEntry({ axis_id: "off_map", label: "地図に出ない軸" }),
    ]);

    expect(labels).toEqual({ on_map: "地図に出る軸", off_map: "地図に出ない軸" });
  });
});

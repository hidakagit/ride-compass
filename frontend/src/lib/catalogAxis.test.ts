// @vitest-environment node
/**
 * `catalogAxis.ts`——軸カタログの1行を、画面が読む軸の形へ移すこと。重み一覧・ramp軸・専用配信の軸・地図のチップの軸は
 * どれもこの変換を通るので、共通の項目の移し方はここで確かめる。
 *
 * 軸は架空のもの（`testing/catalogAxes.ts`）。
 */
import { describe, expect, it } from "vitest";

import { catalogEntry } from "@/testing/catalogAxes";

import { catalogAxisFromEntry } from "./catalogAxis";

describe("catalogAxisFromEntry", () => {
  it("略名が無い軸は、略名に軸の名前を入れる（読み手は補わない）", () => {
    expect(catalogAxisFromEntry(catalogEntry({ label: "軸の名前", chip_label: "略" })).chipLabel).toBe("略");
    expect(catalogAxisFromEntry(catalogEntry({ label: "軸の名前", chip_label: null })).chipLabel).toBe("軸の名前");
  });

  it("アイコンと説明は、未設定なら未設定のまま渡す（汎用のアイコン・(i)を出さないのは読み手が決める）", () => {
    expect(catalogAxisFromEntry(catalogEntry({ icon_id: "shield", panel_hint: "説明" }))).toMatchObject({
      iconId: "shield",
      panelHint: "説明",
    });
    expect(catalogAxisFromEntry(catalogEntry())).toMatchObject({ iconId: undefined, panelHint: undefined });
  });

  it("生値の単位・総量の単位・材料の内訳を渡す", () => {
    const axis = catalogAxisFromEntry(
      catalogEntry({
        raw_value_unit: "回/km",
        raw_value_total_unit: "回",
        material_breakdown: [
          {
            material_id: "m",
            label: "材料",
            dtype: "categorical",
            unit: "",
            share: 1,
            value_labels: { x: "エックス" },
          },
        ],
      }),
    );
    expect(axis).toMatchObject({
      rawValueUnit: "回/km",
      rawValueTotalUnit: "回",
      materialBreakdown: [
        { materialId: "m", label: "材料", dtype: "categorical", unit: "", share: 1, valueLabels: { x: "エックス" } },
      ],
    });
  });
});

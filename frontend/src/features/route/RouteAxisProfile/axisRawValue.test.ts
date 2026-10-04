// @vitest-environment node
/**
 * `features/route/RouteAxisProfile/axisRawValue.ts`——軸の生値と内訳を表示の文へ整える。
 * - `formatAxisRawValue`: 生値を単位付きで書き、総量の単位が来た軸だけ走行距離を掛けた総量（約N）を添える
 * - `formatMaterialBreakdown`: 真偽の材料は該当区間の延長割合、数値の材料は値と単位。ほかの型と値の無い材料は出さない
 * - `formatCategoryBreakdown`: 受け取った並びの先頭の値を、対訳（無ければタグ値のまま）と割合で書く
 * 数値の桁は値の大きさで決まる（10以上は整数・1以上は小数1桁・1未満は有効数字2桁）。
 *
 * ここで見ないもの:
 * - どの軸・材料の値を渡すか、出した文をどこへ並べるか → `RouteAxisProfile.test.tsx`
 */
import { describe, expect, it } from "vitest";

import { formatAxisRawValue, formatCategoryBreakdown, formatMaterialBreakdown } from "./axisRawValue";

describe("formatAxisRawValue", () => {
  it("総量の単位が来た軸は、生値に走行距離を掛けた総量を四捨五入して「約」で添える", () => {
    expect(formatAxisRawValue(0.8, "回/km", "回", 32.5)).toBe("0.8回/km・約26回");
  });

  it.each([
    ["総量の単位が来ない", null, 32.5],
    ["走行距離が無い", "回", null],
    ["走行距離が0", "回", 0],
  ])("%sなら生値だけ", (_label, totalUnit, distanceKm) => {
    expect(formatAxisRawValue(0.8, "回/km", totalUnit, distanceKm)).toBe("0.8回/km");
  });

  it("総量が0.5に満たなければ添えず、0.5からは「約1」と添える", () => {
    expect(formatAxisRawValue(0.049, "回/km", "回", 10)).toBe("0.049回/km");
    expect(formatAxisRawValue(0.05, "回/km", "回", 10)).toBe("0.05回/km・約1回");
  });

  it.each([
    ["生値が無い", undefined, "%"],
    ["単位が無い", 3, null],
    ["単位が空", 3, ""],
  ])("%sなら出さない（null）", (_label, rawValue, unit) => {
    expect(formatAxisRawValue(rawValue, unit, null, 10)).toBeNull();
  });

  it.each([
    [123.4, "123"],
    [10, "10"],
    [9.96, "10.0"],
    [3.14, "3.1"],
    [1, "1.0"],
    [0.5, "0.5"],
    [0.0412, "0.041"],
    [0, "0"],
  ])("生値%sの数字は「%s」", (rawValue, text) => {
    expect(formatAxisRawValue(rawValue, "u", null, null)).toBe(`${text}u`);
  });
});

describe("formatMaterialBreakdown", () => {
  it("真偽の材料は、該当区間の延長割合を%で書く", () => {
    expect(formatMaterialBreakdown({ label: "街灯あり", dtype: "boolean", unit: "" }, 0.675)).toBe("街灯あり 68%");
  });

  it("数値の材料は、値と単位を書く", () => {
    expect(formatMaterialBreakdown({ label: "制限速度", dtype: "numeric", unit: "km/h" }, 42.3)).toBe(
      "制限速度 42km/h",
    );
  });

  it("値の無い材料は出さない（null）", () => {
    expect(formatMaterialBreakdown({ label: "街灯あり", dtype: "boolean", unit: "" }, undefined)).toBeNull();
  });

  it("数値でも真偽でもない型の材料は出さない（null）", () => {
    expect(formatMaterialBreakdown({ label: "道の種類", dtype: "categorical", unit: "" }, 1)).toBeNull();
  });
});

describe("formatCategoryBreakdown", () => {
  const entry = { label: "道の種類", valueLabels: { residential: "住宅街の道" } };

  it("先頭の値を、対訳と割合で書く", () => {
    expect(formatCategoryBreakdown(entry, { residential: 0.624, primary: 0.376 })).toBe("住宅街の道 62%");
  });

  it("並べ替えず、受け取った並びの先頭を出す", () => {
    expect(formatCategoryBreakdown(entry, { primary: 0.1, residential: 0.9 })).toBe("primary 10%");
  });

  it("対訳の無い値・対訳を持たない材料は、タグ値のまま書く", () => {
    expect(formatCategoryBreakdown(entry, { service: 0.4 })).toBe("service 40%");
    expect(formatCategoryBreakdown({ label: "道の種類" }, { residential: 0.4 })).toBe("residential 40%");
  });

  it("割合が来ない・空なら出さない（null）", () => {
    expect(formatCategoryBreakdown(entry, undefined)).toBeNull();
    expect(formatCategoryBreakdown(entry, {})).toBeNull();
  });
});

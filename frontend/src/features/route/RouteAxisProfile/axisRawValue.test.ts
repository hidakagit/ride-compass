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
  it.each([
    ["総量の単位が来ない", null, 32.5],
    ["走行距離が無い", "回", null],
    ["走行距離が0", "回", 0],
  ])("%sなら生値だけ", (_label, totalUnit, distanceKm) => {
    expect(formatAxisRawValue(0.8, "回/km", totalUnit, distanceKm)).toBe("0.8回/km");
  });

  it("総量の単位が来た軸は、生値に走行距離を掛けた総量を四捨五入して「約」で添える。0.5に満たなければ添えない", () => {
    expect(formatAxisRawValue(0.049, "回/km", "回", 10)).toBe("0.049回/km");
    expect(formatAxisRawValue(0.05, "回/km", "回", 10)).toBe("0.05回/km・約1回");
  });

  it.each([
    ["生値が無い", undefined, "%"],
    ["単位が無い", 3, null],
  ])("%sなら出さない（null）", (_label, rawValue, unit) => {
    expect(formatAxisRawValue(rawValue, unit, null, 10)).toBeNull();
  });

  it.each([
    [10, "10"],
    [9.96, "10.0"],
    [1, "1.0"],
    [0.0412, "0.041"],
    [0, "0"],
  ])("生値%sの数字は「%s」", (rawValue, text) => {
    expect(formatAxisRawValue(rawValue, "u", null, null)).toBe(`${text}u`);
  });
});

describe("formatMaterialBreakdown", () => {
  const lit = { label: "街灯あり", dtype: "boolean", unit: "" };

  it.each([
    ["真偽の材料は、該当区間の延長割合を%で書く", lit, 0.675, "街灯あり 68%"],
    ["数値の材料は、値と単位を書く", { label: "制限速度", dtype: "numeric", unit: "km/h" }, 42.3, "制限速度 42km/h"],
    ["値の無い材料は出さない", lit, undefined, null],
    ["数値でも真偽でもない型の材料は出さない", { label: "道の種類", dtype: "categorical", unit: "" }, 1, null],
  ])("%s", (_label, entry, value, text) => {
    expect(formatMaterialBreakdown(entry, value)).toBe(text);
  });
});

describe("formatCategoryBreakdown", () => {
  const entry = { label: "道の種類", valueLabels: { residential: "住宅街の道" } };

  it.each([
    ["先頭の値を、対訳と割合で書く", entry, { residential: 0.624, primary: 0.376 }, "住宅街の道 62%"],
    ["並べ替えずに先頭を出し、対訳の無い値はタグ値のまま", entry, { primary: 0.1, residential: 0.9 }, "primary 10%"],
    ["対訳を持たない材料は、タグ値のまま書く", { label: "道の種類" }, { residential: 0.4 }, "residential 40%"],
    ["割合が来なければ出さない", entry, undefined, null],
  ])("%s", (_label, material, shares, text) => {
    expect(formatCategoryBreakdown(material, shares)).toBe(text);
  });
});

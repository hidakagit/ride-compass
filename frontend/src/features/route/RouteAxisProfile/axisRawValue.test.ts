// @vitest-environment node
import { describe, expect, it } from "vitest";

import { formatAxisRawValue, formatCategoryBreakdown, formatMaterialBreakdown } from "./axisRawValue";

describe("formatAxisRawValue（軸の生値の文）", () => {
  it("生値に単位を付ける。数の桁は大きさで決める（10以上は整数・1以上は小数1桁・1未満は有効数字2桁）", () => {
    expect(formatAxisRawValue(12.46, "%", null, null)).toBe("12%");
    expect(formatAxisRawValue(3.14, "%", null, null)).toBe("3.1%");
    expect(formatAxisRawValue(0.0412, "件/km", null, null)).toBe("0.041件/km");
    expect(formatAxisRawValue(0.08, "件/km", null, null)).toBe("0.08件/km");
    expect(formatAxisRawValue(0, "件/km", null, null)).toBe("0件/km");
    expect(formatAxisRawValue(-2.5, "%", null, null)).toBe("-2.5%");
  });

  it("総量の単位が来た軸だけ、走行距離を掛けた総量を「約N」で添える", () => {
    expect(formatAxisRawValue(0.8, "回/km", "回", 32.4)).toBe("0.8回/km・約26回");
    expect(formatAxisRawValue(0.8, "回/km", null, 32.4)).toBe("0.8回/km");
  });

  it("総量が0.5に満たない・距離が無い・距離が0以下なら、総量は添えない", () => {
    expect(formatAxisRawValue(0.01, "回/km", "回", 10)).toBe("0.01回/km");
    expect(formatAxisRawValue(0.8, "回/km", "回", null)).toBe("0.8回/km");
    expect(formatAxisRawValue(0.8, "回/km", "回", 0)).toBe("0.8回/km");
  });

  it("生値か単位が無ければ出さない", () => {
    expect(formatAxisRawValue(undefined, "%", null, null)).toBeNull();
    expect(formatAxisRawValue(1, null, null, null)).toBeNull();
    expect(formatAxisRawValue(1, "", null, null)).toBeNull();
  });
});

describe("formatMaterialBreakdown（材料の内訳1件）", () => {
  it("真偽値の材料は延長の割合（%）", () => {
    expect(formatMaterialBreakdown({ label: "街灯あり", dtype: "boolean", unit: "" }, 0.684)).toBe("街灯あり 68%");
  });

  it("数値の材料は値と単位", () => {
    expect(formatMaterialBreakdown({ label: "制限速度", dtype: "numeric", unit: "km/h" }, 42.3)).toBe(
      "制限速度 42km/h",
    );
  });

  it("値が無い・有限でない・数値でも真偽値でもない材料は出さない", () => {
    const numeric = { label: "x", dtype: "numeric", unit: "" };
    expect(formatMaterialBreakdown(numeric, undefined)).toBeNull();
    expect(formatMaterialBreakdown(numeric, Number.NaN)).toBeNull();
    expect(formatMaterialBreakdown({ label: "x", dtype: "categorical", unit: "" }, 1)).toBeNull();
  });
});

describe("formatCategoryBreakdown（分類の材料の内訳1件）", () => {
  it("先頭の値（backendが延長の割合の降順で返す）を、対訳の名前と割合で出す", () => {
    const entry = { label: "道の種類", valueLabels: { residential: "住宅街の道" } };
    expect(formatCategoryBreakdown(entry, { residential: 0.62, primary: 0.3 })).toBe("住宅街の道 62%");
  });

  it("対訳の無い値は、タグの値をそのまま出す", () => {
    expect(formatCategoryBreakdown({ label: "道の種類" }, { living_street: 0.5 })).toBe("living_street 50%");
  });

  it("値が無い・割合が有限でなければ出さない", () => {
    expect(formatCategoryBreakdown({ label: "道の種類" }, undefined)).toBeNull();
    expect(formatCategoryBreakdown({ label: "道の種類" }, {})).toBeNull();
    expect(formatCategoryBreakdown({ label: "道の種類" }, { a: Number.NaN })).toBeNull();
  });
});

// @vitest-environment node
import { describe, expect, it } from "vitest";

import { formatAxisRawValue, totalUnitFor } from "./axisRawValue";

describe("totalUnitFor", () => {
  it("距離あたりの単位からは実数の単位が取れる", () => {
    expect(totalUnitFor("回/km")).toBe("回");
  });

  it("距離あたりでない単位はnull（距離を掛けても意味を持たない）", () => {
    expect(totalUnitFor("%")).toBeNull();
    expect(totalUnitFor("")).toBeNull();
  });
});

describe("formatAxisRawValue", () => {
  it("距離あたりの単位なら、経路全体の実数を添える", () => {
    // 0.8回/km × 32.5km ≒ 26回
    expect(formatAxisRawValue(0.8, "回/km", 32.5)).toBe("0.8回/km・約26回");
  });

  it("距離あたりでない単位は実数を添えない", () => {
    expect(formatAxisRawValue(4.2, "%", 32.5)).toBe("4.2%");
  });

  it("値の大きさに応じて桁を変える（行動が変わらない細かさは出さない）", () => {
    expect(formatAxisRawValue(15.4, "回/km", null)).toBe("15回/km");
    expect(formatAxisRawValue(3.2, "回/km", null)).toBe("3.2回/km");
    expect(formatAxisRawValue(0.08, "回/km", null)).toBe("0.08回/km");
  });

  // backendが実際に配信する精度で確かめる。生値は`domain/route.py: merge_axis_raw_values`が
  // 有効数字4桁へ丸めて返すため（T698）、桁の小さい軸では0.0413のような値が届く。
  // 「配信されない値だけを固定したテスト」は、丸め方が変わっても赤くならない。
  it("backendが配信する丸め（有効数字4桁）の値をそのまま読める形で出す", () => {
    expect(formatAxisRawValue(0.0413, "件/(km・年)", 32.5)).toBe("0.041件/(km・年)");
    expect(formatAxisRawValue(0.1234, "件/(km・年)", 32.5)).toBe("0.12件/(km・年)");
    expect(formatAxisRawValue(1.234, "回/km", 32.5)).toBe("1.2回/km・約40回");
    expect(formatAxisRawValue(123.4, "度/km", null)).toBe("123度/km");
  });

  // 統合レビュー第6回の指摘I-5: 1未満を一律小数2桁で出していたため、桁の小さい軸
  // （事故密度は件/(km・年)で代表点0.02/0.1/0.3）の実データが「0.00」に潰れ、
  // 値の無い道と区別できなくなっていた。有効数字2桁を残す。
  it("桁の小さい軸でも値が0へ潰れない", () => {
    expect(formatAxisRawValue(0.041, "件/(km・年)", 32.5)).toBe("0.041件/(km・年)");
    expect(formatAxisRawValue(0.0041, "件/(km・年)", 32.5)).toBe("0.0041件/(km・年)");
    // 本当に0のときだけ0と出る。
    expect(formatAxisRawValue(0, "件/(km・年)", 32.5)).toBe("0件/(km・年)");
  });

  it("実数が1回に満たなければ添えない（「約0回」は情報にならない）", () => {
    expect(formatAxisRawValue(0.01, "回/km", 20)).toBe("0.01回/km");
  });

  it("値や単位が無ければ何も出さない", () => {
    expect(formatAxisRawValue(undefined, "回/km", 20)).toBeNull();
    expect(formatAxisRawValue(0.8, null, 20)).toBeNull();
    expect(formatAxisRawValue(0.8, "", 20)).toBeNull();
  });
});

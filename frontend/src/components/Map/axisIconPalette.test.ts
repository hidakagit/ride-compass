// @vitest-environment node
// axisIconFor（改善計画T310）の純ロジック検証。DOM不要のためnode環境で実行する。

import { describe, expect, it } from "vitest";
import { AXIS_ICON_PALETTE, axisIconFor } from "./axisIconPalette";
import { AxisRampIcon, GradientAxisIcon } from "./icons";

describe("axisIconFor（改善計画T310）", () => {
  it("パレットに登録済みのicon_idはそのアイコンコンポーネントを返す", () => {
    expect(axisIconFor("incline")).toBe(GradientAxisIcon);
  });

  it("未登録のicon_idは汎用フォールバック（AxisRampIcon）を返す", () => {
    expect(axisIconFor("no-such-icon")).toBe(AxisRampIcon);
  });

  it("未設定（null/undefined）は汎用フォールバック（AxisRampIcon）を返す", () => {
    expect(axisIconFor(null)).toBe(AxisRampIcon);
    expect(axisIconFor(undefined)).toBe(AxisRampIcon);
  });

  it("パレットは既存6軸ぶんの意匠 + 新規軸向けスペアを含む（改善計画T310「色々用意しておき」）", () => {
    const ids = Object.keys(AXIS_ICON_PALETTE);
    // 既存6軸（勾配・舗装質・夜間・停止密度・車の圧迫感・事故密度）ぶんの意匠。
    expect(ids).toEqual(
      expect.arrayContaining(["incline", "wave", "crescent-moon", "density-stack", "density-scatter", "warning-triangle"])
    );
    // 新規軸向けにあらかじめ用意したスペア（既存軸のどれにも使われていない汎用形状）。
    expect(ids.length).toBeGreaterThan(6);
  });
});

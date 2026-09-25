// @vitest-environment node
import { describe, expect, it } from "vitest";
import { axisIconFor } from "./axisIconPalette";
import { AxisRampIcon, GradientAxisIcon } from "@/components/ui/icons/icons";

describe("axisIconFor", () => {
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
});

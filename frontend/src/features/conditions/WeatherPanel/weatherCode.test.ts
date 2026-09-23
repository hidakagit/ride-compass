// @vitest-environment node
import { describe, expect, it } from "vitest";

import { vocabulary } from "@/types/generated/vocabulary";

import { getWeatherCodeDisplay, WEATHER_CATEGORY_ICON } from "./weatherCode";

describe("getWeatherCodeDisplay（予報の天気コード→アイコンと名前）", () => {
  it("宣言された天気コードは、その分類のアイコンと名前になる", () => {
    const codes = vocabulary.weatherCategories.flatMap((category) =>
      category.codes.map((code) => ({ category, code })),
    );
    expect(codes).not.toHaveLength(0);
    for (const { category, code } of codes) {
      expect(getWeatherCodeDisplay(code)).toEqual({ Icon: WEATHER_CATEGORY_ICON[category.key], label: category.label });
    }
  });

  it("宣言に無いコードは、既定の分類へ倒す", () => {
    const declared = new Set(vocabulary.weatherCategories.flatMap((category) => category.codes));
    const unknown = Math.max(...declared) + 1;
    const fallback = vocabulary.weatherCategories.find((c) => c.key === vocabulary.weatherCategoryFallback)!;
    expect(getWeatherCodeDisplay(unknown)?.label).toBe(fallback.label);
  });

  it("コードが無ければ何も出さない", () => {
    expect(getWeatherCodeDisplay(null)).toBeNull();
  });
});

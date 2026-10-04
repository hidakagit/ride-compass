// @vitest-environment node
import { describe, expect, it } from "vitest";

import { MoonIcon, SunIcon } from "@/components/ui/icons/icons";
import { vocabulary } from "@/types/generated/vocabulary";

import { getAmedasWeatherDisplay } from "./amedasWeatherIcon";
import { WEATHER_CATEGORY_ICON, WEATHER_CATEGORY_LABEL } from "./weatherCode";

describe("getAmedasWeatherDisplay", () => {
  it("晴れだけは昼夜で絵を変える", () => {
    expect(getAmedasWeatherDisplay(0, true)).toEqual({ Icon: SunIcon, label: WEATHER_CATEGORY_LABEL.clear });
    expect(getAmedasWeatherDisplay(0, false)).toEqual({ Icon: MoonIcon, label: WEATHER_CATEGORY_LABEL.clear });
  });

  it("晴れ以外は、分類の名前と分類のアイコンになる", () => {
    const rain = vocabulary.weatherCategories.find((category) => category.key === "rain")!;
    expect(getAmedasWeatherDisplay(rain.codes[0], true)).toEqual({
      Icon: WEATHER_CATEGORY_ICON.rain,
      label: rain.label,
    });
  });

  it("天気が決まっていない・宣言に無いコードは、別の天気に見せず何も出さない", () => {
    const declared = new Set(vocabulary.weatherCategories.flatMap((category) => category.codes));
    expect(getAmedasWeatherDisplay(null, true)).toBeNull();
    expect(getAmedasWeatherDisplay(Math.max(...declared) + 1, true)).toBeNull();
  });
});

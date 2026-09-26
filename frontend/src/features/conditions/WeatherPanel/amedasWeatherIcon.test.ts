// @vitest-environment node
import { describe, expect, it } from "vitest";

import { MoonIcon, SunIcon } from "@/components/ui/icons/icons";

import { getAmedasWeatherDisplay } from "./amedasWeatherIcon";
import { WEATHER_CATEGORY_ICON, WEATHER_CATEGORY_LABEL } from "./weatherCode";

describe("getAmedasWeatherDisplay", () => {
  it("晴れだけは昼夜で絵を変える", () => {
    expect(getAmedasWeatherDisplay(0, true)).toEqual({ Icon: SunIcon, label: WEATHER_CATEGORY_LABEL.clear });
    expect(getAmedasWeatherDisplay(0, false)).toEqual({ Icon: MoonIcon, label: WEATHER_CATEGORY_LABEL.clear });
  });

  it("晴れ以外は、予報と同じ分類のアイコンと名前", () => {
    expect(getAmedasWeatherDisplay(71, false)).toEqual({
      Icon: WEATHER_CATEGORY_ICON.snow,
      label: WEATHER_CATEGORY_LABEL.snow,
    });
  });

  it("天気が決まっていなければ何も出さない", () => {
    expect(getAmedasWeatherDisplay(null, true)).toBeNull();
  });
});

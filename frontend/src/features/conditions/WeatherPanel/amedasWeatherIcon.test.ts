// @vitest-environment node
import { describe, expect, it } from "vitest";

import { MoonIcon, SunIcon } from "@/components/ui/icons/icons";

import { classifyAmedasWeather, getAmedasWeatherDisplay } from "./amedasWeatherIcon";
import { WEATHER_CATEGORY_ICON, WEATHER_CATEGORY_LABEL } from "./weatherCode";

describe("classifyAmedasWeather（アメダスの実測からの簡易な天気）", () => {
  it("降水があれば、気温2℃以下は雪・それより高いか気温が無ければ雨", () => {
    expect(classifyAmedasWeather(0.5, 10, 2)).toBe("snow");
    expect(classifyAmedasWeather(0.5, 10, 2.1)).toBe("rain");
    expect(classifyAmedasWeather(0.5, null, null)).toBe("rain");
  });

  it("降水が無ければ、日照があれば晴れ・無ければくもり", () => {
    expect(classifyAmedasWeather(0, 3, 20)).toBe("clear");
    expect(classifyAmedasWeather(null, 0, 20)).toBe("cloudy");
  });

  it("降水も日照も読めなければ決めない", () => {
    expect(classifyAmedasWeather(null, null, 20)).toBeNull();
    expect(classifyAmedasWeather(0, null, 20)).toBeNull();
  });
});

describe("getAmedasWeatherDisplay", () => {
  it("晴れだけは昼夜で絵を変える", () => {
    expect(getAmedasWeatherDisplay("clear", true)).toEqual({ Icon: SunIcon, label: WEATHER_CATEGORY_LABEL.clear });
    expect(getAmedasWeatherDisplay("clear", false)).toEqual({ Icon: MoonIcon, label: WEATHER_CATEGORY_LABEL.clear });
  });

  it("晴れ以外は、予報と同じ分類のアイコンと名前", () => {
    expect(getAmedasWeatherDisplay("rain", false)).toEqual({
      Icon: WEATHER_CATEGORY_ICON.rain,
      label: WEATHER_CATEGORY_LABEL.rain,
    });
  });

  it("天気が決まっていなければ何も出さない", () => {
    expect(getAmedasWeatherDisplay(null, true)).toBeNull();
  });
});

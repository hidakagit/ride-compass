// @vitest-environment node
import { describe, expect, it } from "vitest";
import { getWeatherCodeDisplay } from "./weatherCode";

// backendが実際に返すWMO天気コード（domain/weather.py: derive_weather_codeのdocstringが
// 宣言する契約）。frontend側にこの表が無いと、backendが新しいコードを返すようになっても
// 未知コードのフォールバック（`?? "cloudy"`）で雨や雪まで黙ってくもり扱いになる。
// 両側に境界値表を持つのはcompass_label（WindBearingSlider.test.ts ⇔ test_geo.py）と同じ形。
const BACKEND_WEATHER_CODES = [0, 1, 2, 3, 61, 63, 65, 71, 73, 75] as const;

const EXPECTED_LABEL: Record<number, string> = {
  0: "晴れ",
  1: "晴れ",
  2: "くもり",
  3: "くもり",
  61: "雨",
  63: "雨",
  65: "雨",
  71: "雪",
  73: "雪",
  75: "雪",
};

describe("getWeatherCodeDisplay", () => {
  it("backendが返す全コードが、フォールバックへ落ちずに意図どおりのラベルになる", () => {
    for (const code of BACKEND_WEATHER_CODES) {
      const display = getWeatherCodeDisplay(code, 1);
      expect(display, `code=${code}`).not.toBeNull();
      expect(display!.label, `code=${code}`).toBe(EXPECTED_LABEL[code]);
    }
  });

  it("weather_codeが無い（null）ならnullを返す（呼び出し元はチップ自体を出さない）", () => {
    expect(getWeatherCodeDisplay(null, 1)).toBeNull();
  });

  it("未知コードはくもりへ倒す（アイコンを消すより粗く出す方がまし）", () => {
    // 表に無いコードでもnullにはしない。ただし「雨・雪が黙ってくもりになる」のを避けるため、
    // 上のテストがbackendの実際の出力を全件押さえている。
    expect(getWeatherCodeDisplay(9999, 1)?.label).toBe("くもり");
  });

  it("晴れだけ昼夜でアイコンが変わる", () => {
    const day = getWeatherCodeDisplay(0, 1);
    const night = getWeatherCodeDisplay(0, 0);
    expect(day!.Icon).not.toBe(night!.Icon);
    // 晴れ以外は昼夜で変えない。
    expect(getWeatherCodeDisplay(63, 1)!.Icon).toBe(getWeatherCodeDisplay(63, 0)!.Icon);
  });
});

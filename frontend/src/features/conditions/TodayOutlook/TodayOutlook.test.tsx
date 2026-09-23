import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { WeatherConditions } from "@/types/weather";

import TodayOutlook from "./TodayOutlook";

const EMPTY = {
  precipitation_max_mm: null,
  wind_speed_max_ms: null,
  temperature_max_c: null,
  temperature_min_c: null,
  sunrise: null,
  sunset: null,
  today_periods: [],
};
const weather = (overrides: Partial<WeatherConditions> = {}) => ({ ...EMPTY, ...overrides }) as WeatherConditions;

async function open() {
  await userEvent.click(screen.getByRole("button", { name: "今日の見通しを表示" }));
  return screen.findByText("今日の見通し");
}

/** 見出しの付いた1項目の値（見出しの次の文字）。 */
const stat = (heading: string) => screen.getByText(heading).nextElementSibling?.textContent;

describe("TodayOutlook 取得の状態", () => {
  it("見通しが無く失敗したら、警戒の見た目の入口を出し、開くと失敗の理由を出す", async () => {
    render(<TodayOutlook weather={null} loading={false} error="混雑しています" />);
    await userEvent.click(screen.getByRole("button", { name: "今日の見通しの取得に失敗しました" }));
    expect(await screen.findByText("取得に失敗しました: 混雑しています")).toBeInTheDocument();
  });

  it("見通しがあれば、直近の取り直しが失敗していても見通しを出す", () => {
    render(<TodayOutlook weather={weather({ wind_speed_max_ms: 5 })} loading={false} error="混雑しています" />);
    expect(screen.getByRole("button", { name: "今日の見通しを表示" })).toBeInTheDocument();
  });

  it("読み込み中・見通しが無い・出せる値が1つも無い間は、入口を出さない", () => {
    const { container, rerender } = render(
      <TodayOutlook weather={weather({ wind_speed_max_ms: 5 })} loading error={null} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<TodayOutlook weather={null} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<TodayOutlook weather={weather()} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("TodayOutlook 1日の値", () => {
  it("最大の降水量・風速は小数1桁、気温は最低〜最高を整数で出す", async () => {
    render(
      <TodayOutlook
        weather={weather({
          precipitation_max_mm: 2.46,
          wind_speed_max_ms: 7.04,
          temperature_min_c: 17.6,
          temperature_max_c: 25.4,
        })}
        loading={false}
        error={null}
      />,
    );
    await open();
    expect(stat("降水量（最大）")).toBe("2.5mm/h");
    expect(stat("風（最大）")).toBe("7.0m/s");
    expect(stat("気温")).toBe("18℃〜25℃");
  });

  it("値の無い項目は出さない。気温は片方だけでも出す", async () => {
    render(<TodayOutlook weather={weather({ temperature_max_c: 25 })} loading={false} error={null} />);
    await open();
    expect(screen.queryByText("降水量（最大）")).not.toBeInTheDocument();
    expect(screen.queryByText("日の出・日没")).not.toBeInTheDocument();
    expect(stat("気温")).toBe("25℃");
  });

  it("日の出・日没は日本時間で出し、片方が無い・読めないときは「--:--」", async () => {
    render(
      <TodayOutlook
        weather={weather({ sunrise: "2026-09-23T20:30:00Z", sunset: "壊れた値" })}
        loading={false}
        error={null}
      />,
    );
    await open();
    expect(stat("日の出・日没")).toBe("05:30〜--:--");
  });

  it("日の出だけ無くても、日没は出す", async () => {
    render(<TodayOutlook weather={weather({ sunset: "2026-09-24T08:40:00Z" })} loading={false} error={null} />);
    await open();
    expect(stat("日の出・日没")).toBe("--:--〜17:40");
  });
});

describe("TodayOutlook 天気の流れ", () => {
  const periods = [
    { period: "06:00", weather_code: 0, temperature_c: 18.4, precipitation_mm: 0.05 },
    { period: "08:00", weather_code: null, temperature_c: null, precipitation_mm: 1.26 },
    { period: "昼", weather_code: 61, temperature_c: 22, precipitation_mm: null },
  ];

  it("コマごとに時・天気・気温（整数）・降水量を出す。降らない見込みと値の無いものは「-」", async () => {
    render(<TodayOutlook weather={weather({ today_periods: periods } as never)} loading={false} error={null} />);
    await open();
    const slots = screen.getByText("天気の流れ").nextElementSibling!.children;
    expect([...slots].map((slot) => slot.textContent)).toEqual(["6時18℃-", "8時--1.3mm", "昼22℃-"]);
    expect(slots[0].querySelector("svg")).not.toBeNull();
    expect(slots[1].querySelector("svg")).toBeNull();
  });

  it("コマが無ければ、流れの欄は出さない", async () => {
    render(<TodayOutlook weather={weather({ wind_speed_max_ms: 3 })} loading={false} error={null} />);
    await open();
    expect(screen.queryByText("天気の流れ")).not.toBeInTheDocument();
  });
});

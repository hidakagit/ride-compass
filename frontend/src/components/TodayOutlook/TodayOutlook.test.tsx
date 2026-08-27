import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { WeatherConditions } from "@/types/weather";
import TodayOutlook from "./TodayOutlook";

function makeWeather(overrides: Partial<WeatherConditions>): WeatherConditions {
  return {
    temperature_c: 20,
    apparent_temperature_c: null,
    wind_speed_ms: 3,
    wind_direction_deg: 90,
    wind_direction_label: "東",
    wind_gusts_ms: null,
    precipitation_probability_percent: null,
    precipitation_mm: null,
    uv_index: null,
    observed_at: "2026-08-28T00:00:00Z",
    weather_code: null,
    is_day: null,
    sunset: null,
    precipitation_probability_max_percent: null,
    wind_speed_max_ms: null,
    temperature_max_c: null,
    temperature_min_c: null,
    ...overrides,
  };
}

describe("TodayOutlook（改善計画T385）", () => {
  it("weatherがnullの場合は何も描画しない", () => {
    const { container } = render(<TodayOutlook weather={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("今日の見通し4項目が全てnullの場合はトグル自体を出さない", () => {
    const { container } = render(<TodayOutlook weather={makeWeather({})} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("sunsetがあればトグルボタンを表示する", () => {
    render(<TodayOutlook weather={makeWeather({ sunset: "2026-08-28T18:24" })} />);
    expect(screen.getByRole("button", { name: "今日の見通しを表示" })).toBeInTheDocument();
  });

  it("ボタンを押すと日没時刻(時:分)がPopoverで見える", async () => {
    const user = userEvent.setup();
    render(<TodayOutlook weather={makeWeather({ sunset: "2026-08-28T18:24" })} />);

    await user.click(screen.getByRole("button", { name: "今日の見通しを表示" }));

    expect(screen.getByText("18:24")).toBeInTheDocument();
    expect(screen.getByText("日没")).toBeInTheDocument();
  });

  it("降水確率(最大)・風(最大)・気温レンジがある場合はそれぞれ表示する", async () => {
    const user = userEvent.setup();
    render(
      <TodayOutlook
        weather={makeWeather({
          precipitation_probability_max_percent: 70.4,
          wind_speed_max_ms: 4.2,
          temperature_max_c: 27.0,
          temperature_min_c: 15.4,
        })}
      />
    );

    await user.click(screen.getByRole("button", { name: "今日の見通しを表示" }));

    expect(screen.getByText("降水確率（最大）")).toBeInTheDocument();
    expect(screen.getByText("70")).toBeInTheDocument();
    expect(screen.getByText("風（最大）")).toBeInTheDocument();
    expect(screen.getByText("4.2")).toBeInTheDocument();
    expect(screen.getByText("気温")).toBeInTheDocument();
    expect(screen.getByText(/15℃〜27℃/)).toBeInTheDocument();
  });

  it("値が無い項目は行ごと表示しない", async () => {
    const user = userEvent.setup();
    render(<TodayOutlook weather={makeWeather({ sunset: "2026-08-28T18:24" })} />);

    await user.click(screen.getByRole("button", { name: "今日の見通しを表示" }));

    expect(screen.queryByText("降水確率（最大）")).not.toBeInTheDocument();
    expect(screen.queryByText("風（最大）")).not.toBeInTheDocument();
    expect(screen.queryByText("気温")).not.toBeInTheDocument();
  });
});

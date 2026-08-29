import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { WeatherConditions, WeatherPeriodOutlook } from "@/types/weather";
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
    sunrise: null,
    sunset: null,
    precipitation_probability_max_percent: null,
    wind_speed_max_ms: null,
    temperature_max_c: null,
    temperature_min_c: null,
    uv_index_max: null,
    today_periods: [],
    ...overrides,
  };
}

function makePeriod(overrides: Partial<WeatherPeriodOutlook>): WeatherPeriodOutlook {
  return {
    period: "12:00",
    weather_code: 1,
    temperature_c: 27.0,
    precipitation_probability_percent: 20,
    ...overrides,
  };
}

// 改善計画T387フォローアップ（2026-08-29）: 日の出/日没は常設ヘッダー（WeatherPanel）へ
// 移設したため、TodayOutlookの表示対象から外れた（旧「夜明け前/日没前の切り替え」テストは
// WeatherPanel.test.tsxへ移設）。
describe("TodayOutlook（改善計画T385・T387フォローアップ）", () => {
  it("weatherがnullでloading/errorも無い場合は何も描画しない", () => {
    const { container } = render(<TodayOutlook weather={null} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("loading中は何も描画しない（トグルのチラつきを避ける）", () => {
    const { container } = render(<TodayOutlook weather={null} loading={true} error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("errorがある場合は警戒色のトリガーを表示し、開くとエラー内容が見える", async () => {
    const user = userEvent.setup();
    render(<TodayOutlook weather={null} loading={false} error="取得に失敗しました" />);

    const trigger = screen.getByRole("button", { name: "今日の見通しの取得に失敗しました" });
    expect(trigger).toBeInTheDocument();

    await user.click(trigger);

    expect(screen.getByText(/取得に失敗しました/)).toBeInTheDocument();
  });

  it("今日の見通し4項目が全てnullの場合はトグル自体を出さない", () => {
    const { container } = render(<TodayOutlook weather={makeWeather({})} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
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
        loading={false}
        error={null}
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
    render(
      <TodayOutlook weather={makeWeather({ uv_index_max: 8.5 })} loading={false} error={null} />
    );

    await user.click(screen.getByRole("button", { name: "今日の見通しを表示" }));

    expect(screen.queryByText("降水確率（最大）")).not.toBeInTheDocument();
    expect(screen.queryByText("風（最大）")).not.toBeInTheDocument();
    expect(screen.queryByText("気温")).not.toBeInTheDocument();
  });

  it("UV指数（最大）がある場合はトグルを出し値を表示する（ユーザー指摘: 常設ヘッダーの" +
    "UV指数はスマホから見えづらいため確実にタップで開けるここへ表示する）", async () => {
    const user = userEvent.setup();
    render(<TodayOutlook weather={makeWeather({ uv_index_max: 8.5 })} loading={false} error={null} />);

    await user.click(screen.getByRole("button", { name: "今日の見通しを表示" }));

    expect(screen.getByText("UV指数（最大）")).toBeInTheDocument();
    expect(screen.getByText("8.5")).toBeInTheDocument();
  });

  it("today_periodsが8コマある場合は天気の流れとして時刻・気温・降水確率を表示する", async () => {
    const user = userEvent.setup();
    const periods = [
      makePeriod({ period: "06:00", weather_code: 1, temperature_c: 22.0, precipitation_probability_percent: 10 }),
      makePeriod({ period: "08:00", weather_code: 2, temperature_c: 24.0, precipitation_probability_percent: 15 }),
      makePeriod({ period: "10:00", weather_code: 61, temperature_c: 26.5, precipitation_probability_percent: 60 }),
      makePeriod({ period: "12:00" }),
      makePeriod({ period: "14:00" }),
      makePeriod({ period: "16:00" }),
      makePeriod({ period: "18:00" }),
      makePeriod({ period: "20:00", temperature_c: 25.0, precipitation_probability_percent: 50 }),
    ];
    render(<TodayOutlook weather={makeWeather({ today_periods: periods })} loading={false} error={null} />);

    await user.click(screen.getByRole("button", { name: "今日の見通しを表示" }));

    expect(screen.getByText("天気の流れ")).toBeInTheDocument();
    expect(screen.getByText("6時")).toBeInTheDocument();
    expect(screen.getByText("20時")).toBeInTheDocument();
    expect(screen.getByText("22℃")).toBeInTheDocument();
    expect(screen.getByText("10%")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("today_periodsが空の場合は天気の流れセクションを出さない", async () => {
    const user = userEvent.setup();
    render(
      <TodayOutlook weather={makeWeather({ uv_index_max: 8.5 })} loading={false} error={null} />
    );

    await user.click(screen.getByRole("button", { name: "今日の見通しを表示" }));

    expect(screen.queryByText("天気の流れ")).not.toBeInTheDocument();
  });

  it("コマのweather_codeがnullでも気温・降水確率は表示しアイコン欠落を代替表示で埋める", async () => {
    const user = userEvent.setup();
    const periods = [makePeriod({ period: "06:00", weather_code: null, temperature_c: null, precipitation_probability_percent: null })];
    render(<TodayOutlook weather={makeWeather({ today_periods: periods })} loading={false} error={null} />);

    await user.click(screen.getByRole("button", { name: "今日の見通しを表示" }));

    expect(screen.getByText("6時")).toBeInTheDocument();
    expect(screen.getAllByText("-").length).toBeGreaterThanOrEqual(2);
  });
});

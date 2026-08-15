import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { WeatherConditions } from "@/types/weather";
import WeatherPanel from "./WeatherPanel";

function makeWeather(overrides: Partial<WeatherConditions>): WeatherConditions {
  return {
    temperature_c: 20,
    wind_speed_ms: 3,
    wind_direction_deg: 90,
    wind_direction_label: "東",
    precipitation_probability_percent: null,
    observed_at: "2026-08-14T00:00:00Z",
    ...overrides,
  };
}

describe("WeatherPanel", () => {
  it("loading中は取得中メッセージを表示する", () => {
    render(<WeatherPanel weather={null} loading={true} error={null} />);
    expect(screen.getByText("天候取得中...")).toBeInTheDocument();
  });

  it("errorがある場合はエラーテキストを表示し天候テキストは表示しない", () => {
    render(<WeatherPanel weather={null} loading={false} error="失敗しました" />);
    expect(screen.getByText("失敗しました")).toBeInTheDocument();
    expect(screen.queryByText(/の風/)).not.toBeInTheDocument();
  });

  it("weatherがnullでloading/errorも無い場合は何も描画しない", () => {
    const { container } = render(<WeatherPanel weather={null} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("weatherがある場合は気温・風向・風速を表示する", () => {
    const weather = makeWeather({ temperature_c: 21.34, wind_direction_label: "北西", wind_speed_ms: 4.56 });
    render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(screen.getByText(/21\.3℃/)).toBeInTheDocument();
    expect(screen.getByText(/北西の風/)).toBeInTheDocument();
    expect(screen.getByText(/4\.6 m\/s/)).toBeInTheDocument();
    expect(screen.queryByText(/降水確率/)).not.toBeInTheDocument();
  });

  it("precipitation_probability_percentがある場合は降水確率を四捨五入して表示する", () => {
    const weather = makeWeather({ precipitation_probability_percent: 42.6 });
    render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(screen.getByText(/降水確率 43%/)).toBeInTheDocument();
  });
});

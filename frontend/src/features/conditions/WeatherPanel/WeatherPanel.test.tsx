import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AmedasObservation } from "@/types/weather";

import WeatherPanel from "./WeatherPanel";
import { WEATHER_CATEGORY_LABEL } from "./weatherCode";

const NOW = new Date("2026-09-24T12:00:00+09:00");

const observation = (overrides: Partial<AmedasObservation> = {}) =>
  ({
    station_name: "東京",
    observed_at: "2026-09-24T11:50:00+09:00",
    temperature_c: 21.44,
    apparent_temperature_c: 19.96,
    wind_speed_ms: 3.25,
    wind_direction: { deg: 90, label: "東" },
    precipitation_10min_mm: 0,
    weather_code: 0,
    twilight: { sunrise: "2026-09-24T05:30:00+09:00", sunset: "2026-09-24T17:40:00+09:00" },
    ...overrides,
  }) as AmedasObservation;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("WeatherPanel 取得の状態", () => {
  it("観測値が無く取得中なら、取得中と出す", () => {
    render(<WeatherPanel amedas={null} loading error={null} />);
    expect(screen.getByText("天候取得中...")).toBeInTheDocument();
  });

  it("観測値が無く失敗したら、取得できないとだけ出し、理由は補足に回す", () => {
    render(<WeatherPanel amedas={null} loading={false} error="混雑しています" />);
    expect(screen.getByText("観測値を取得できません")).toHaveAttribute("title", "混雑しています");
  });

  it("観測値があれば、取り直し中・直近の失敗でも観測値を出す", () => {
    render(<WeatherPanel amedas={observation()} loading error="混雑しています" />);
    expect(screen.getByText("気温:").parentElement).toHaveTextContent("21.4℃");
  });

  it("観測値も失敗も無ければ何も出さない", () => {
    const { container } = render(<WeatherPanel amedas={null} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("WeatherPanel 観測値", () => {
  it("気温・風速と風向・10分間の降水量を小数1桁で出し、風の矢印は吹いていく向き（来る向きの反対）を指す", () => {
    render(<WeatherPanel amedas={observation({ precipitation_10min_mm: 1.25 })} loading={false} error={null} />);
    expect(screen.getByText("気温:").parentElement).toHaveTextContent("21.4℃");
    const wind = screen.getByText("東の風:").parentElement!;
    expect(wind).toHaveTextContent("3.3m/s");
    expect((wind.firstElementChild as HTMLElement).style.transform).toBe("rotate(270deg)");
    expect(screen.getByText("降水量:").parentElement).toHaveTextContent("1.3mm");
  });

  it("気温が無ければ「-」、風・降水量は値が無ければ出さない", () => {
    render(
      <WeatherPanel
        amedas={observation({
          temperature_c: null,
          apparent_temperature_c: null,
          wind_speed_ms: null,
          precipitation_10min_mm: null,
        })}
        loading={false}
        error={null}
      />,
    );
    expect(screen.getByText("気温:").parentElement).toHaveTextContent("-℃");
    expect(screen.queryByText(/の風:/)).not.toBeInTheDocument();
    expect(screen.queryByText("降水量:")).not.toBeInTheDocument();
  });

  it("天気はbackendが実測から導いたコードで出し、日の出から日の入りまでを昼とする", () => {
    const { unmount } = render(<WeatherPanel amedas={observation()} loading={false} error={null} />);
    const dayIcon = screen.getByText(/^天気:/).parentElement!.innerHTML;
    unmount();
    vi.setSystemTime(new Date("2026-09-24T20:00:00+09:00"));
    render(<WeatherPanel amedas={observation()} loading={false} error={null} />);
    expect(screen.getByText(/^天気:/).parentElement!.innerHTML).not.toBe(dayIcon);
  });

  it("日の出・日の入りが分からなければ昼として扱う", () => {
    vi.setSystemTime(new Date("2026-09-24T20:00:00+09:00"));
    const { unmount } = render(<WeatherPanel amedas={observation({ twilight: null })} loading={false} error={null} />);
    const unknown = screen.getByText(/^天気:/).parentElement!.innerHTML;
    unmount();
    vi.setSystemTime(NOW);
    render(<WeatherPanel amedas={observation()} loading={false} error={null} />);
    expect(screen.getByText(/^天気:/).parentElement!.innerHTML).toBe(unknown);
  });

  it("天気を決められなければ、天気は出さない", () => {
    render(
      <WeatherPanel
        amedas={observation({ precipitation_10min_mm: null, weather_code: null })}
        loading={false}
        error={null}
      />,
    );
    expect(screen.queryByText(/^天気:/)).not.toBeInTheDocument();
  });
});

describe("WeatherPanel 観測の出所", () => {
  it("観測値を押すと、アメダスの観測であることと観測所名・観測の時刻（日本時間）、数値ごとの意味が開く", async () => {
    render(
      <WeatherPanel
        amedas={observation({
          station_name: "練馬",
          observed_at: "2026-09-24T02:50:00Z",
          precipitation_10min_mm: 1.25,
        })}
        loading={false}
        error={null}
      />,
    );
    expect(screen.queryByText("アメダスの観測")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /気温:/ }));

    const panel = screen.getByRole("dialog");
    expect(panel).toHaveTextContent("アメダスの観測");
    expect(panel).toHaveTextContent("練馬11:50");
    expect(panel).toHaveTextContent("気温21.4℃（体感 20.0℃）");
    expect(panel).toHaveTextContent("風東の風 3.3m/s");
    expect(panel).toHaveTextContent("直近10分間の降水量1.3mm");
    expect(panel).toHaveTextContent(`天気${WEATHER_CATEGORY_LABEL.clear}`);
  });

  it("体感温度・風・降水量・天気が無ければ、パネルにもその行を出さない", async () => {
    render(
      <WeatherPanel
        amedas={observation({
          temperature_c: null,
          apparent_temperature_c: null,
          wind_speed_ms: null,
          precipitation_10min_mm: null,
          weather_code: null,
        })}
        loading={false}
        error={null}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /気温:/ }));

    const panel = screen.getByRole("dialog");
    expect(panel).toHaveTextContent("気温-℃");
    expect(panel).not.toHaveTextContent("体感");
    expect(panel).not.toHaveTextContent("風");
    expect(panel).not.toHaveTextContent("降水量");
    expect(panel).not.toHaveTextContent("天気");
  });
});

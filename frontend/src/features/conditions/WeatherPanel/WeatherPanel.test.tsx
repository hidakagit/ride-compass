import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AmedasObservation } from "@/types/weather";

import WeatherPanel from "./WeatherPanel";

const NOW = new Date("2026-09-24T12:00:00+09:00");

const observation = (overrides: Partial<AmedasObservation> = {}) =>
  ({
    temperature_c: 21.44,
    apparent_temperature_c: 19.96,
    wind_speed_ms: 3.25,
    wind_direction_deg: 90,
    wind_direction_label: "東",
    precipitation_10min_mm: 0,
    sunshine_10min_minutes: 10,
    weather_code: 0,
    sunrise: "2026-09-24T05:30:00+09:00",
    sunset: "2026-09-24T17:40:00+09:00",
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
    expect(screen.queryByText("観測値を取得できません")).not.toBeInTheDocument();
    expect(screen.getByText("気温:").parentElement).toHaveTextContent("21.4℃");
  });

  it("観測値も失敗も無ければ何も出さない", () => {
    const { container } = render(<WeatherPanel amedas={null} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("WeatherPanel 観測値", () => {
  it("気温（体感は補足）・風速と風向・10分間の降水量を小数1桁で出す", () => {
    render(<WeatherPanel amedas={observation({ precipitation_10min_mm: 1.25 })} loading={false} error={null} />);
    const temperature = screen.getByText("気温:").parentElement!;
    expect(temperature).toHaveTextContent("21.4℃");
    expect(temperature).toHaveAttribute("title", "体感 20.0℃");
    const wind = screen.getByText("東の風:").parentElement!;
    expect(wind).toHaveTextContent("3.3m/s");
    expect(wind).toHaveAttribute("title", "東の風");
    expect(screen.getByText("降水量:").parentElement).toHaveTextContent("1.3mm");
  });

  it("風向の呼び名が無くても風速は出し、補足は付けない", () => {
    render(<WeatherPanel amedas={observation({ wind_direction_label: null })} loading={false} error={null} />);
    const wind = screen.getByText("m/s").closest("[class]")!.parentElement!.parentElement!;
    expect(wind).toHaveTextContent("3.3m/s");
    expect(wind).not.toHaveAttribute("title");
  });

  it("風の矢印は、風が吹いていく向き（来る向きの反対）を指す", () => {
    render(<WeatherPanel amedas={observation({ wind_direction_deg: 90 })} loading={false} error={null} />);
    const arrow = screen.getByText("東の風:").parentElement!.firstElementChild as HTMLElement;
    expect(arrow.style.transform).toBe("rotate(270deg)");
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
    expect(screen.getByText("気温:").parentElement).not.toHaveAttribute("title");
    expect(screen.queryByText(/の風:/)).not.toBeInTheDocument();
    expect(screen.queryByText("降水量:")).not.toBeInTheDocument();
  });

  it("天気はbackendが実測から導いたコードで出し、日の出から日の入りまでを昼とする", () => {
    const { unmount } = render(<WeatherPanel amedas={observation()} loading={false} error={null} />);
    expect(screen.getByText(/^天気:/).parentElement!.querySelector("svg")).not.toBeNull();
    const dayIcon = screen.getByText(/^天気:/).parentElement!.innerHTML;
    unmount();
    vi.setSystemTime(new Date("2026-09-24T20:00:00+09:00"));
    render(<WeatherPanel amedas={observation()} loading={false} error={null} />);
    expect(screen.getByText(/^天気:/).parentElement!.innerHTML).not.toBe(dayIcon);
  });

  it("日の出・日の入りが分からなければ昼として扱う", () => {
    vi.setSystemTime(new Date("2026-09-24T20:00:00+09:00"));
    const { unmount } = render(
      <WeatherPanel amedas={observation({ sunrise: null, sunset: null })} loading={false} error={null} />,
    );
    const unknown = screen.getByText(/^天気:/).parentElement!.innerHTML;
    unmount();
    vi.setSystemTime(NOW);
    render(<WeatherPanel amedas={observation()} loading={false} error={null} />);
    expect(screen.getByText(/^天気:/).parentElement!.innerHTML).toBe(unknown);
  });

  it("天気を決められなければ、天気は出さない", () => {
    render(
      <WeatherPanel
        amedas={observation({ precipitation_10min_mm: null, sunshine_10min_minutes: null, weather_code: null })}
        loading={false}
        error={null}
      />,
    );
    expect(screen.queryByText(/^天気:/)).not.toBeInTheDocument();
  });
});

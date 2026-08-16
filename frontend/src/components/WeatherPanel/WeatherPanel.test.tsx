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
    // 値と単位（℃/m/s）は視覚的に区別するため別要素（.unit）に分けているので、getByTextの
    // 単一要素マッチでは拾えない（DOM Testing Libraryの既知の制約: 複数要素にまたがるテキストは
    // 通常のTextMatchでは見つからない）。container.textContentで結合テキストを確認する。
    const weather = makeWeather({ temperature_c: 21.34, wind_direction_label: "北西", wind_speed_ms: 4.56 });
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(container.textContent).toMatch(/21\.3℃/);
    expect(container.textContent).toMatch(/北西の風/);
    expect(container.textContent).toMatch(/4\.6\s*m\/s/);
    expect(container.textContent).not.toMatch(/降水確率/);
  });

  it("precipitation_probability_percentがある場合は降水確率を四捨五入して表示する", () => {
    const weather = makeWeather({ precipitation_probability_percent: 42.6 });
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(container.textContent).toMatch(/降水確率.*43%/);
  });

  it("項目ごとにアイコン(気温・風・降水確率)を表示し、区切りは項目間のみに出す", () => {
    // "/"区切りの1文だと区切りの"/"と単位"m/s"の"/"が混ざって見えるという実機フィードバックを
    // 受け、項目ごとのアイコン+区切り線の並びへ変更した（T61）。svgアイコン3種と区切り線2本
    // （気温|風|降水確率の間、降水確率が無い場合は1本）が出ることを確認する。
    const weather = makeWeather({ precipitation_probability_percent: 10 });
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(container.querySelectorAll("svg")).toHaveLength(3);
    // 区切り線はspan[aria-hidden]（svgアイコン自身もaria-hiddenを持つため、タグで絞る）
    expect(container.querySelectorAll('span[aria-hidden="true"]')).toHaveLength(2);
  });
});

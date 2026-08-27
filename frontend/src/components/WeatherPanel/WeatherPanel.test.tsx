import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { WeatherConditions } from "@/types/weather";
import WeatherPanel from "./WeatherPanel";

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
    observed_at: "2026-08-14T00:00:00Z",
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

  // 改善計画T172: 突風・降水量・UV指数・体感温度を追加。既存の3項目（気温・風・降水確率）を
  // 壊さず、値がある場合だけ併記する。上部バー最適化（スマホ実機フィードバック）で
  // 体感温度・突風・降水量は常時表示の括弧書きからtitle属性（長押し/ホバー）へ格下げした
  // （狭い幅でのCJKテキスト折り返し対策、1行化優先）ため、textContentではなくtitle属性を見る。
  it("apparent_temperature_cがある場合は気温チップのtitleに体感温度を併記する", () => {
    const weather = makeWeather({ apparent_temperature_c: 27.1 });
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(container.querySelector('[title*="体感 27.1"]')).toBeInTheDocument();
  });

  it("wind_gusts_msがある場合は風チップのtitleに突風を併記する", () => {
    const weather = makeWeather({ wind_gusts_ms: 8.24 });
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(container.querySelector('[title*="突風 8.2"]')).toBeInTheDocument();
  });

  it("precipitation_mmがある場合は降水量チップのtitleにmm\\/hを併記する(確率が無くても単独で表示される)", () => {
    const weather = makeWeather({ precipitation_probability_percent: null, precipitation_mm: 1.25 });
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(container.querySelector('[title*="1.3mm/h"]')).toBeInTheDocument();
  });

  // 改善計画T385: UV指数専用チップを撤去し、weather_code+is_dayから決まる天気アイコンへ
  // 置き換えた（夜間はuv_indexが常に0.0になり情報価値が無いままヘッダーを圧迫していたため）。
  it("weather_codeがある場合は天気アイコンのチップを表示し、titleにラベルを持つ", () => {
    const weather = makeWeather({ weather_code: 3, is_day: 1 }); // 3=くもり
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(container.querySelector('[title*="くもり"]')).toBeInTheDocument();
  });

  it("weather_codeが無い場合は天気アイコンのチップを表示しない", () => {
    const weather = makeWeather({ weather_code: null });
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(container.querySelector('[title*="くもり"]')).not.toBeInTheDocument();
  });

  it("is_day=0(夜間)かつ快晴(weather_code=0)の場合は月アイコン用のtitleになる", () => {
    const weather = makeWeather({ weather_code: 0, is_day: 0 });
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(container.querySelector('[title*="快晴"]')).toBeInTheDocument();
  });

  it("uv_indexがある場合は天気アイコンのtitleにUV指数を併記する", () => {
    const weather = makeWeather({ weather_code: 1, is_day: 1, uv_index: 7.4 });
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    expect(container.querySelector('[title*="UV指数 7.4"]')).toBeInTheDocument();
  });

  it("wind_direction_degぶん矢印を回転させる(+180度、吹いてくる方向ではなく吹いていく方向を指す)", () => {
    const weather = makeWeather({ wind_direction_deg: 90 });
    const { container } = render(<WeatherPanel weather={weather} loading={false} error={null} />);

    const arrow = container.querySelector('[style*="rotate"]');
    expect(arrow).toBeInTheDocument();
    expect(arrow?.getAttribute("style")).toMatch(/rotate\(270deg\)/);
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

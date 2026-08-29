import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AmedasObservation } from "@/types/weather";
import WeatherPanel from "./WeatherPanel";

// 改善計画T387フォローアップ（2026-08-29、方針「常設エリアは実測値、今日の見通しは予測値」）:
// WeatherPanelはOpen-Meteo（WeatherConditions）ではなく最寄りアメダス観測所の実測値
// （AmedasObservation）を表示する。降水確率→実測降水量、天気アイコン→アメダス実測ベースの
// 簡易分類（amedasWeatherIcon.ts）、日の出/日没チップを新規追加、突風はアメダスに
// フィールド自体が無いため非表示（旧テストのwind_gusts_ms関連は削除）。
function makeAmedas(overrides: Partial<AmedasObservation>): AmedasObservation {
  return {
    station_id: "44132",
    station_name: "東京",
    latitude: 35.69,
    longitude: 139.76,
    observed_at: "2026-08-14T00:00:00+09:00",
    temperature_c: 20,
    apparent_temperature_c: null,
    wind_speed_ms: 3,
    wind_direction_deg: 90,
    wind_direction_label: "東",
    precipitation_10min_mm: null,
    sunshine_10min_minutes: null,
    sunrise: null,
    sunset: null,
    ...overrides,
  };
}

describe("WeatherPanel", () => {
  it("loading中は取得中メッセージを表示する", () => {
    render(<WeatherPanel amedas={null} loading={true} error={null} />);
    expect(screen.getByText("天候取得中...")).toBeInTheDocument();
  });

  it("errorがある場合はエラーテキストを表示し天候テキストは表示しない", () => {
    render(<WeatherPanel amedas={null} loading={false} error="失敗しました" />);
    expect(screen.getByText("失敗しました")).toBeInTheDocument();
    expect(screen.queryByText(/の風/)).not.toBeInTheDocument();
  });

  it("amedasがnullでloading/errorも無い場合は何も描画しない", () => {
    const { container } = render(<WeatherPanel amedas={null} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("amedasがある場合は気温・風向・風速を表示する", () => {
    const amedas = makeAmedas({ temperature_c: 21.34, wind_direction_label: "北西", wind_speed_ms: 4.56 });
    const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

    expect(container.textContent).toMatch(/21\.3℃/);
    expect(container.textContent).toMatch(/北西の風/);
    expect(container.textContent).toMatch(/4\.6\s*m\/s/);
  });

  it("apparent_temperature_cがある場合は気温チップのtitleに体感温度を併記する", () => {
    const amedas = makeAmedas({ apparent_temperature_c: 27.1 });
    const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

    expect(container.querySelector('[title*="体感 27.1"]')).toBeInTheDocument();
  });

  it("precipitation_10min_mmがある場合は実測降水量を表示する（確率ではなく実測mm）", () => {
    const amedas = makeAmedas({ precipitation_10min_mm: 1.25 });
    const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

    expect(container.textContent).toMatch(/1\.3\s*mm/);
    expect(container.querySelector('[title="直近10分間の降水量"]')).toBeInTheDocument();
  });

  it("precipitation_10min_mmが無い場合は降水チップを表示しない", () => {
    const amedas = makeAmedas({ precipitation_10min_mm: null });
    const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

    expect(container.querySelector('[title="直近10分間の降水量"]')).not.toBeInTheDocument();
  });

  it("wind_speed_ms/wind_direction_degが無い場合は風チップを表示しない（アメダス欠測想定）", () => {
    const amedas = makeAmedas({ wind_speed_ms: null, wind_direction_deg: null });
    const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

    expect(container.textContent).not.toMatch(/の風/);
  });

  describe("天気アイコンの簡易分類（precipitation_10min_mm・sunshine_10min_minutes・temperature_c由来）", () => {
    it("降水量>0かつ気温>2℃なら雨アイコン", () => {
      const amedas = makeAmedas({ precipitation_10min_mm: 0.5, temperature_c: 10 });
      const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

      expect(container.querySelector('[title="雨"]')).toBeInTheDocument();
    });

    it("降水量>0かつ気温<=2℃なら雪アイコン", () => {
      const amedas = makeAmedas({ precipitation_10min_mm: 0.5, temperature_c: 0 });
      const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

      expect(container.querySelector('[title="雪"]')).toBeInTheDocument();
    });

    it("降水量0かつ日照時間>0なら晴れアイコン", () => {
      const amedas = makeAmedas({ precipitation_10min_mm: 0, sunshine_10min_minutes: 8 });
      const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

      expect(container.querySelector('[title="晴れ"]')).toBeInTheDocument();
    });

    it("降水量0かつ日照時間0ならくもりアイコン", () => {
      const amedas = makeAmedas({ precipitation_10min_mm: 0, sunshine_10min_minutes: 0 });
      const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

      expect(container.querySelector('[title="くもり"]')).toBeInTheDocument();
    });

    it("降水量・日照時間のいずれも無ければ天気アイコンを表示しない", () => {
      const amedas = makeAmedas({ precipitation_10min_mm: null, sunshine_10min_minutes: null });
      const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

      expect(container.querySelector('[title="晴れ"], [title="くもり"], [title="雨"], [title="雪"]')).not.toBeInTheDocument();
    });
  });

  describe("日の出/日没チップ（改善計画T387フォローアップ、常設ヘッダーへ移設）", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("日の出前なら↑（上昇）矢印付きで日の出時刻を表示する（改善計画T387フォローアップ2、" +
      "「アイコン+時刻だけだと何の時刻か分からない」というユーザー指摘への対応）", () => {
      vi.spyOn(Date, "now").mockReturnValue(new Date("2026-08-28T04:00:00").getTime());
      const amedas = makeAmedas({ sunrise: "2026-08-28T05:12:00+09:00", sunset: "2026-08-28T18:24:00+09:00" });
      const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

      expect(container.textContent).toMatch(/↑05:12/);
      expect(container.querySelector('[title*="日の出"]')).toBeInTheDocument();
    });

    it("日中は↓（下降）矢印付きで日没時刻を表示する", () => {
      vi.spyOn(Date, "now").mockReturnValue(new Date("2026-08-28T12:00:00").getTime());
      const amedas = makeAmedas({ sunrise: "2026-08-28T05:12:00+09:00", sunset: "2026-08-28T18:24:00+09:00" });
      const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

      expect(container.textContent).toMatch(/↓18:24/);
      expect(container.querySelector('[title*="日没"]')).toBeInTheDocument();
    });

    it("sunrise/sunsetが無く天気も判定できない場合はチップを表示しない", () => {
      const amedas = makeAmedas({ sunrise: null, sunset: null });
      const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

      expect(container.querySelector('[title*="日の出"], [title*="日没"]')).not.toBeInTheDocument();
    });

    it("天気アイコンと日の出/日没は1チップに統合され、両方の情報を持つ（改善計画T387" +
      "フォローアップ、ヘッダーのバッジ見切れ対策でチップ数を増やさないための統合）", () => {
      vi.spyOn(Date, "now").mockReturnValue(new Date("2026-08-28T12:00:00").getTime());
      const amedas = makeAmedas({
        precipitation_10min_mm: 0,
        sunshine_10min_minutes: 8,
        sunrise: "2026-08-28T05:12:00+09:00",
        sunset: "2026-08-28T18:24:00+09:00",
      });
      const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

      // 天気アイコン用・日の出日没用の2チップに分かれず、1つのチップへ両方収まる
      // （svgアイコンが1個のみ、titleに両方の情報を持つ）。矢印(↓)が時刻の意味を補う。
      const chip = container.querySelector('[title*="晴れ"][title*="日没"]');
      expect(chip).toBeInTheDocument();
      expect(chip?.textContent).toMatch(/↓18:24/);
    });
  });

  it("wind_direction_degぶん矢印を回転させる(+180度、吹いてくる方向ではなく吹いていく方向を指す)", () => {
    const amedas = makeAmedas({ wind_direction_deg: 90 });
    const { container } = render(<WeatherPanel amedas={amedas} loading={false} error={null} />);

    const arrow = container.querySelector('[style*="rotate"]');
    expect(arrow).toBeInTheDocument();
    expect(arrow?.getAttribute("style")).toMatch(/rotate\(270deg\)/);
  });
});

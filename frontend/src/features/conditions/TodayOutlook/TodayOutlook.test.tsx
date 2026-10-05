import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { WeatherConditions } from "@/types/weather";

import TodayOutlook from "./TodayOutlook";

const EMPTY = {
  precipitation_max_mm: null,
  wind_speed_max_ms: null,
  temperature_range: null,
  twilight: null,
  today_periods: [],
  today_period_interval_hours: 3,
};
const TWILIGHT = { sunrise: "2026-09-23T20:30:00Z", sunset: "2026-09-24T08:40:00Z" };
const weather = (overrides: Partial<WeatherConditions> = {}) => ({ ...EMPTY, ...overrides }) as WeatherConditions;

async function open() {
  await userEvent.click(screen.getByRole("button", { name: "今日のモデルの計算値を表示" }));
  return screen.findByRole("dialog");
}

/** 見出しの付いた1項目の値（見出しの次の文字）。 */
const stat = (heading: string) => screen.getByText(heading).nextElementSibling?.textContent;

describe("TodayOutlook 取得の状態", () => {
  it("見通しが無く失敗したら、警戒の見た目の入口を出し、開くと失敗の理由を出す", async () => {
    render(<TodayOutlook weather={null} loading={false} error="混雑しています" />);
    await userEvent.click(screen.getByRole("button", { name: "今日のモデルの計算値の取得に失敗しました" }));
    expect(await screen.findByText("取得に失敗しました: 混雑しています")).toBeInTheDocument();
  });

  it("見通しがあれば、直近の取り直しが失敗していても見通しを出す", () => {
    render(<TodayOutlook weather={weather({ wind_speed_max_ms: 5 })} loading={false} error="混雑しています" />);
    expect(screen.getByRole("button", { name: "今日のモデルの計算値を表示" })).toBeInTheDocument();
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
          temperature_range: { min_c: 17.6, max_c: 25.4 },
        })}
        loading={false}
        error={null}
      />,
    );
    await open();
    expect(stat("降水量[最大]")).toBe("2.5mm/h");
    expect(stat("風[最大]")).toBe("7.0m/s");
    expect(stat("気温")).toBe("18℃〜25℃");
  });

  it("値の無い項目とコマの欄は出さない", async () => {
    render(<TodayOutlook weather={weather({ wind_speed_max_ms: 3 })} loading={false} error={null} />);
    await open();
    expect(screen.queryByText("降水量[最大]")).not.toBeInTheDocument();
    expect(screen.queryByText("気温")).not.toBeInTheDocument();
    expect(screen.queryByText("日の出・日没")).not.toBeInTheDocument();
    expect(screen.queryByText("3時間ごと")).not.toBeInTheDocument();
  });

  it("日の出・日没は日本時間で出し、読めない時刻は「--:--」", async () => {
    render(
      <TodayOutlook
        weather={weather({ twilight: { sunrise: "2026-09-23T20:30:00Z", sunset: "壊れた値" } })}
        loading={false}
        error={null}
      />,
    );
    await open();
    expect(stat("日の出・日没")).toBe("05:30〜--:--");
  });

  it("日の出・日没は天文計算の値のため、「モデルの計算値」の見出しより上に置く", async () => {
    render(
      <TodayOutlook weather={weather({ twilight: TWILIGHT, wind_speed_max_ms: 5 })} loading={false} error={null} />,
    );
    await open();
    const heading = screen.getByText("今日のモデルの計算値");
    expect(screen.getByText("日の出・日没").compareDocumentPosition(heading)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("日の出・日没しか無いときは、「モデルの計算値」の見出しを出さない", async () => {
    render(<TodayOutlook weather={weather({ twilight: TWILIGHT })} loading={false} error={null} />);
    await open();
    expect(screen.queryByText("今日のモデルの計算値")).not.toBeInTheDocument();
  });
});

describe("TodayOutlook 一定間隔のコマ", () => {
  const periods = [
    { period: "06:00", temperature_c: 18.4, precipitation_mm: 0.05 },
    { period: "08:00", temperature_c: null, precipitation_mm: 1.26 },
    { period: "昼", temperature_c: 22, precipitation_mm: null },
  ];

  it("コマの並びに届いた間隔を添え、コマごとに時・気温（整数）・降水量を出す。降らない量と値の無いものは「-」", async () => {
    render(<TodayOutlook weather={weather({ today_periods: periods } as never)} loading={false} error={null} />);
    await open();
    const slots = screen.getByText("3時間ごと").nextElementSibling!.children;
    expect([...slots].map((slot) => slot.textContent)).toEqual(["6時18℃-", "8時-1.3mm", "昼22℃-"]);
  });
});

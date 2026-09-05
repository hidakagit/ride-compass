import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RideConditionBar, { clampSpeedKmh, formatDepartureLabel } from "./RideConditionBar";

// 出発時刻ポップオーバーはDynamicLayerTimeSliderを内包する。EmblaCarouselがマウント時に
// window.matchMedia/IntersectionObserver/ResizeObserverを無条件に呼ぶため、jsdom環境では
// 未定義のままだと例外になる（DynamicLayerTimeSlider.test.tsxと同じ理由）。
beforeEach(() => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    media: "",
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
  } as unknown as MediaQueryList);

  class IntersectionObserverMock {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
    takeRecords = vi.fn(() => []);
  }
  window.IntersectionObserver = IntersectionObserverMock as unknown as typeof IntersectionObserver;

  class ResizeObserverMock {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
  }
  window.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
});

function Harness({ initialTime, onTime }: { initialTime: Date; onTime?: (t: Date) => void }) {
  const [time, setTime] = useState(initialTime);
  const [speed, setSpeed] = useState(20);
  return (
    <RideConditionBar
      departureTime={time}
      onDepartureTimeChange={(t) => {
        setTime(t);
        onTime?.(t);
      }}
      speedKmh={speed}
      onSpeedKmhChange={setSpeed}
    />
  );
}

describe("formatDepartureLabel", () => {
  it("当日は時:分のみ、別日は月/日を前置する", () => {
    const now = new Date(2026, 8, 5, 8, 0);
    expect(formatDepartureLabel(new Date(2026, 8, 5, 9, 30), now)).toBe("9:30");
    expect(formatDepartureLabel(new Date(2026, 8, 6, 9, 5), now)).toBe("9/6 9:05");
  });
});

describe("clampSpeedKmh", () => {
  it("範囲外・非数値は範囲内へ丸める", () => {
    expect(clampSpeedKmh(80)).toBe(60);
    expect(clampSpeedKmh(1)).toBe(5);
    expect(clampSpeedKmh(Number.NaN)).toBe(20);
    expect(clampSpeedKmh(24.6)).toBe(25);
  });
});

describe("RideConditionBar", () => {
  it("出発チップに絶対時刻を表示し、クイックボタンで出発時刻を更新する", async () => {
    const user = userEvent.setup();
    const onTime = vi.fn();
    const initial = new Date();
    initial.setHours(9, 30, 0, 0);
    render(<Harness initialTime={initial} onTime={onTime} />);

    expect(screen.getByRole("button", { name: "出発時刻: 9:30（タップで変更）" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "出発時刻: 9:30（タップで変更）" }));
    const before = Date.now();
    await user.click(screen.getByRole("button", { name: "+1h" }));
    expect(onTime).toHaveBeenCalledTimes(1);
    const picked = onTime.mock.calls[0][0] as Date;
    expect(picked.getTime()).toBeGreaterThanOrEqual(before + 3_600_000 - 1000);
  });

  it("出発チップをタップするとドラッグ式タイムラインが開き、キーボード操作で出発時刻を進められる", async () => {
    const user = userEvent.setup();
    const onTime = vi.fn();
    const initial = new Date();
    render(<Harness initialTime={initial} onTime={onTime} />);

    await user.click(screen.getByRole("button", { name: `出発時刻: ${formatDepartureLabel(initial)}（タップで変更）` }));
    const ruler = screen.getByRole("slider", { name: "出発時刻" });
    ruler.focus();
    await user.keyboard("{ArrowRight}");

    expect(onTime).toHaveBeenCalledTimes(1);
    const picked = onTime.mock.calls[0][0] as Date;
    expect(picked.getTime()).toBeGreaterThan(initial.getTime());
  });

  it("「現在」ボタンで実時刻へ戻す", async () => {
    const user = userEvent.setup();
    const onTime = vi.fn();
    const past = new Date(Date.now() - 2 * 60 * 60_000);
    render(<Harness initialTime={past} onTime={onTime} />);

    await user.click(screen.getByRole("button", { name: `出発時刻: ${formatDepartureLabel(past)}（タップで変更）` }));
    const before = Date.now();
    await user.click(screen.getByRole("button", { name: "出発時刻を現在に戻す" }));

    expect(onTime).toHaveBeenCalledTimes(1);
    const picked = onTime.mock.calls[0][0] as Date;
    expect(picked.getTime()).toBeGreaterThanOrEqual(before);
  });

  it("速度チップから数値入力で想定速度を変更すると範囲内へ丸めて反映する", async () => {
    const user = userEvent.setup();
    render(<Harness initialTime={new Date()} />);

    await user.click(screen.getByRole("button", { name: "想定速度: 20 km/h（タップで変更）" }));
    const input = screen.getByRole("spinbutton", { name: "想定速度（km/h）" });
    await user.clear(input);
    await user.type(input, "80");
    await user.tab();
    expect(screen.getByRole("button", { name: "想定速度: 60 km/h（タップで変更）" })).toBeInTheDocument();
  });
});

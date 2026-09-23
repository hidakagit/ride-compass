import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RideConditionBar from "./RideConditionBar";
import { clampSpeedKmh, formatDepartureLabel, toDatetimeLocalValue } from "@/lib/rideConditions";
import { stubEmblaBrowserApis } from "@/testing/emblaBrowserApis";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

// 出発時刻ポップオーバーはDynamicLayerTimeSliderを内包するため、Emblaが要るAPIを用意する。
beforeEach(stubEmblaBrowserApis);

function Harness({
  initialTime,
  onTime,
  onNow,
}: {
  initialTime: Date;
  onTime?: (t: Date) => void;
  onNow?: () => void;
}) {
  const [time, setTime] = useState(initialTime);
  const [speed, setSpeed] = useState(20);
  return (
    <RideConditionBar
      departureTime={time}
      onDepartureTimeChange={(t) => {
        setTime(t);
        onTime?.(t);
      }}
      onDepartureNow={() => onNow?.()}
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
  // 上限・下限・既定値は源泉が配る（route-generate-config.json）。値を書くと、
  // backendで調整しただけでこのテストが落ちる。**丸めの性質**だけを見る。
  const { min_assumed_speed_kmh: min, max_assumed_speed_kmh: max } = routeGenerateConfig;

  it("上と下の外はそれぞれの端へ寄せる", () => {
    expect(clampSpeedKmh(max + 100)).toBe(max);
    expect(clampSpeedKmh(min - 100)).toBe(min);
  });

  it("数でない入力は既定値へ倒す（NaNのまま持ち回らない）", () => {
    expect(clampSpeedKmh(Number.NaN)).toBe(routeGenerateConfig.default_assumed_speed_kmh);
  });

  it("小数は四捨五入する", () => {
    const inRange = Math.floor((min + max) / 2);
    expect(clampSpeedKmh(inRange + 0.6)).toBe(inRange + 1);
    expect(clampSpeedKmh(inRange + 0.4)).toBe(inRange);
  });
});

describe("RideConditionBar", () => {
  // 画面に出す値・読み上げ（aria-label）・ホバー（title）は同じ文字列から作る。
  // 片方だけ古くなると、見えている値と読み上げの値が食い違う。
  it("ボタンに出す現在値は、titleとaria-labelに載る値と同じ", () => {
    const initial = new Date();
    render(<Harness initialTime={initial} />);

    const label = formatDepartureLabel(initial);
    const departure = screen.getByRole("button", { name: `出発時刻: ${label}（タップで変更）` });
    expect(departure).toHaveAttribute("title", `出発時刻: ${label}`);
    expect(departure).toHaveTextContent(label);

    const speed = screen.getByRole("button", { name: "想定速度: 20km/h（タップで変更）" });
    expect(speed).toHaveAttribute("title", "想定速度: 20km/h");
    expect(speed).toHaveTextContent("20km/h");
  });

  it("別の日を選ぶと、ボタンの値は日付と時刻の2行になる", () => {
    const tomorrow = new Date(Date.now() + 24 * 3600 * 1000);
    tomorrow.setHours(12, 40, 0, 0);
    render(<Harness initialTime={tomorrow} />);

    const label = formatDepartureLabel(tomorrow);
    const [datePart, timePart] = label.split(" ");
    expect(datePart).toBe(`${tomorrow.getMonth() + 1}/${tomorrow.getDate()}`);
    expect(timePart).toBe("12:40");
    const departure = screen.getByRole("button", { name: `出発時刻: ${label}（タップで変更）` });
    expect(departure).toHaveAttribute("title", `出発時刻: ${label}`);
    // 日付と時刻は別々の行（要素）に出る
    expect(within(departure).getByText(datePart)).not.toBe(within(departure).getByText(timePart));
  });

  it("出発チップをタップするとドラッグ式タイムラインが開き、キーボード操作で出発時刻を進められる", async () => {
    const user = userEvent.setup();
    const onTime = vi.fn();
    const initial = new Date();
    render(<Harness initialTime={initial} onTime={onTime} />);

    await user.click(
      screen.getByRole("button", { name: `出発時刻: ${formatDepartureLabel(initial)}（タップで変更）` }),
    );
    const ruler = screen.getByRole("slider", { name: "出発時刻" });
    ruler.focus();
    await user.keyboard("{ArrowRight}");

    expect(onTime).toHaveBeenCalledTimes(1);
    const picked = onTime.mock.calls[0][0] as Date;
    expect(picked.getTime()).toBeGreaterThan(initial.getTime());
  });

  // 「今」は時刻を選ぶのとは別の操作。現在時刻を渡して代用すると、その値でピン留めされ、
  // 実況の更新から取り残されて降水・雷が黙って消える（T859が直した欠陥がそこで復活する）。
  it("「現在」ボタンは時刻の指定ではなく、追従へ戻す操作を呼ぶ", async () => {
    const user = userEvent.setup();
    const onTime = vi.fn();
    const onNow = vi.fn();
    // タイムラインは開いた時点（≒現在時刻）以降しか目盛りを持たないため、「現在」ボタンが
    // 無効化されない（index !== currentIndex になる）ことを確かめるには未来の時刻を使う。
    const future = new Date(Date.now() + 2 * 60 * 60_000);
    render(<Harness initialTime={future} onTime={onTime} onNow={onNow} />);

    await user.click(screen.getByRole("button", { name: `出発時刻: ${formatDepartureLabel(future)}（タップで変更）` }));
    await user.click(screen.getByRole("button", { name: "出発時刻を現在に戻す" }));

    expect(onNow).toHaveBeenCalledTimes(1);
    expect(onTime).not.toHaveBeenCalled();
  });

  it("出発チップをタップすると日時入力欄が開き、直接指定した日時をそのまま反映する", async () => {
    const user = userEvent.setup();
    const onTime = vi.fn();
    const initial = new Date();
    initial.setHours(9, 30, 0, 0);
    render(<Harness initialTime={initial} onTime={onTime} />);

    await user.click(
      screen.getByRole("button", { name: `出発時刻: ${formatDepartureLabel(initial)}（タップで変更）` }),
    );
    const input = screen.getByLabelText("出発日時を直接指定") as HTMLInputElement;
    expect(input.value).toBe(toDatetimeLocalValue(initial));

    const next = new Date(initial);
    next.setDate(next.getDate() + 1);
    next.setHours(14, 15, 0, 0);
    // datetime-local入力欄はセグメント単位の編集UIのため、jsdom上ではuserEvent.typeで
    // 打鍵を再現できない（BackendLogsPanel.test.tsxのコピー操作と同種の既知の制約）。
    // fireEvent.changeで値を直接設定する。
    fireEvent.change(input, { target: { value: toDatetimeLocalValue(next) } });

    expect(onTime).toHaveBeenCalled();
    const picked = onTime.mock.calls[onTime.mock.calls.length - 1][0] as Date;
    expect(picked.getTime()).toBe(next.getTime());
  });

  it("速度チップから数値入力で想定速度を変更すると範囲内へ丸めて反映する", async () => {
    const user = userEvent.setup();
    render(<Harness initialTime={new Date()} />);

    await user.click(screen.getByRole("button", { name: "想定速度: 20km/h（タップで変更）" }));
    const input = screen.getByRole("spinbutton", { name: "想定速度（km/h）" });
    await user.clear(input);
    await user.type(input, "80");
    await user.tab();
    expect(screen.getByRole("button", { name: "想定速度: 60km/h（タップで変更）" })).toHaveAttribute(
      "title",
      "想定速度: 60km/h",
    );
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import RideConditionBar from "./RideConditionBar";

// 時刻のルーラーのドラッグはEmbla（ライブラリ）の持ち物。ここでは位置合わせを受けるだけの代役にする。
vi.mock("embla-carousel-react", () => ({
  default: () => [() => {}, { scrollTo: vi.fn(), on: vi.fn(), off: vi.fn(), selectedScrollSnap: () => 0 }],
}));
vi.mock("embla-carousel-wheel-gestures", () => ({ WheelGesturesPlugin: () => ({}) }));

const jst = (text: string) => new Date(`${text}+09:00`);
const NOW = jst("2026-09-24T09:07");
const { min_assumed_speed_kmh: MIN, max_assumed_speed_kmh: MAX } = routeGenerateConfig;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

type Props = React.ComponentProps<typeof RideConditionBar>;

function renderBar(overrides: Partial<Props> = {}) {
  const props: Props = {
    departureTime: jst("2026-09-24T09:05"),
    onDepartureTimeChange: vi.fn(),
    onDepartureNow: vi.fn(),
    speedKmh: 20,
    onSpeedKmhChange: vi.fn(),
    ...overrides,
  };
  render(<RideConditionBar {...props} />);
  return props;
}

describe("RideConditionBar 出発時刻", () => {
  it("今日の出発時刻は時刻だけを1行で出す", () => {
    renderBar();
    const button = screen.getByRole("button", { name: "出発時刻: 9:05（タップで変更）" });
    expect(button).toHaveAttribute("title", "出発時刻: 9:05");
    expect([...button.lastElementChild!.children].map((line) => line.textContent)).toEqual(["9:05"]);
  });

  it("別の日の出発時刻は、日付と時刻を2行に分けて出す（列の幅に収める）", () => {
    renderBar({ departureTime: jst("2026-09-25T13:00") });
    const button = screen.getByRole("button", { name: "出発時刻: 9/25 13:00（タップで変更）" });
    expect([...button.lastElementChild!.children].map((line) => line.textContent)).toEqual(["9/25", "13:00"]);
  });

  it("開くと、日時の入力欄に日本時間で今の出発時刻を入れて出し、直接指定した日時を日本時間として渡す", async () => {
    const props = renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^出発時刻:/ }));
    const input = await screen.findByLabelText("出発日時を直接指定");
    expect(input).toHaveValue("2026-09-24T09:05");
    fireEvent.change(input, { target: { value: "2026-09-26T07:30" } });
    expect(props.onDepartureTimeChange).toHaveBeenCalledWith(jst("2026-09-26T07:30"));
  });

  it("入力欄を空にしても、出発時刻は変えない", async () => {
    const props = renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^出発時刻:/ }));
    fireEvent.change(await screen.findByLabelText("出発日時を直接指定"), { target: { value: "" } });
    expect(props.onDepartureTimeChange).not.toHaveBeenCalled();
  });

  it("開いた時刻から作った目盛りで、今の出発時刻に最も近いコマを選んだ状態にする", async () => {
    renderBar({ departureTime: jst("2026-09-24T09:17") });
    await userEvent.click(screen.getByRole("button", { name: /^出発時刻:/ }));
    // 目盛りは開いた時刻（9:07）を5分刻みへ切り下げた9:05から始まる。9:17に最も近いのは9:15。
    expect(await screen.findByRole("slider", { name: "出発時刻" })).toHaveAttribute("aria-valuetext", "9/24 09:15");
  });

  it("閉じて開き直すと、開き直した時刻から目盛りを作り直す", async () => {
    renderBar({ departureTime: jst("2026-09-24T09:05") });
    const trigger = screen.getByRole("button", { name: /^出発時刻:/ });
    await userEvent.click(trigger);
    expect(await screen.findByRole("slider", { name: "出発時刻" })).toHaveAttribute("aria-valuetext", "9/24 09:05");
    await userEvent.click(trigger);
    vi.setSystemTime(jst("2026-09-24T10:02"));
    await userEvent.click(trigger);
    // 目盛りは開き直した10:00から始まり、9:05に最も近いのは先頭の10:00。
    expect(await screen.findByRole("slider", { name: "出発時刻" })).toHaveAttribute("aria-valuetext", "9/24 10:00");
  });

  it("「今」の目盛りを選び直したら、その時刻に固定せず「今」への追従へ戻す（放置して過去になり、予報から外れないように）", async () => {
    const props = renderBar({ departureTime: jst("2026-09-24T09:10") });
    await userEvent.click(screen.getByRole("button", { name: /^出発時刻:/ }));
    // 開いた9:07の「今」の目盛りは9:05。9:10から1つ前へ戻すとそこに当たる。
    await userEvent.click(await screen.findByRole("button", { name: "出発時刻を1つ前へ" }));
    expect(props.onDepartureNow).toHaveBeenCalled();
    expect(props.onDepartureTimeChange).not.toHaveBeenCalled();
  });

  it("目盛りで選んだコマの時刻を出発時刻にし、「現在」は今への追従へ戻す", async () => {
    const props = renderBar({ departureTime: jst("2026-09-24T09:15") });
    await userEvent.click(screen.getByRole("button", { name: /^出発時刻:/ }));
    await userEvent.click(await screen.findByRole("button", { name: "出発時刻を1つ次へ" }));
    expect(props.onDepartureTimeChange).toHaveBeenCalledWith(jst("2026-09-24T09:20"));
    await userEvent.click(screen.getByRole("button", { name: "出発時刻を現在に戻す" }));
    expect(props.onDepartureNow).toHaveBeenCalled();
  });
});

describe("RideConditionBar 想定速度", () => {
  it("今の想定速度を出す", () => {
    renderBar({ speedKmh: 22 });
    const button = screen.getByRole("button", { name: "想定速度: 22km/h（タップで変更）" });
    expect(button).toHaveTextContent("22km/h");
  });

  it("スライダーはbackendが受け付ける範囲で動かし、動かした値を渡す", async () => {
    const props = renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^想定速度:/ }));
    const slider = await screen.findByRole("slider", { name: "想定速度スライダー" });
    expect(slider).toHaveAttribute("min", String(MIN));
    expect(slider).toHaveAttribute("max", String(MAX));
    fireEvent.change(slider, { target: { value: "24" } });
    expect(props.onSpeedKmhChange).toHaveBeenCalledWith(24);
  });

  it("数値欄は確定したときに渡し、範囲の外の値は範囲へ収める", async () => {
    const props = renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^想定速度:/ }));
    const input = await screen.findByLabelText("想定速度（km/h）");
    await userEvent.clear(input);
    await userEvent.type(input, String(MAX + 10));
    expect(props.onSpeedKmhChange).not.toHaveBeenCalled();
    await userEvent.keyboard("{Enter}");
    expect(props.onSpeedKmhChange).toHaveBeenCalledWith(MAX);
  });
});

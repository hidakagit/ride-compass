import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DynamicLayerTimeSlider, { type DynamicLayerTimeSliderFrame } from "./DynamicLayerTimeSlider";

// ドラッグ・ホイール・吸着はEmbla（ライブラリ）が持つ。ここでは差し替えた代役で、
// 「Emblaが選んだコマを報告する」「外から変わった位置へEmblaを動かす」つなぎだけを見る。
const embla = vi.hoisted(() => {
  const listeners = new Map<string, () => void>();
  const api = {
    selected: 0,
    scrollTo: vi.fn(),
    selectedScrollSnap: () => api.selected,
    on: (event: string, handler: () => void) => listeners.set(event, handler),
    off: (event: string) => listeners.delete(event),
    /** Emblaが最寄りのコマを選び直したことにする。 */
    select(index: number) {
      api.selected = index;
      listeners.get("select")?.();
    },
  };
  return api;
});
vi.mock("embla-carousel-react", () => ({ default: () => [() => {}, embla] }));
vi.mock("embla-carousel-wheel-gestures", () => ({ WheelGesturesPlugin: () => ({}) }));

const FRAMES: DynamicLayerTimeSliderFrame[] = [
  { label: "9/24 09:55", tickLabel: "55" },
  { label: "9/24 10:00", hourMark: true, tickLabel: "10:00" },
  { label: "9/24 11:00", hourMark: true },
];

beforeEach(() => {
  embla.scrollTo.mockClear();
  embla.selected = 0;
});

function renderSlider(index: number, currentIndex = 0) {
  const onIndexChange = vi.fn();
  const onNow = vi.fn();
  const view = render(
    <DynamicLayerTimeSlider
      frames={FRAMES}
      index={index}
      onIndexChange={onIndexChange}
      currentIndex={currentIndex}
      onNow={onNow}
      ariaLabel="出発時刻"
    />,
  );
  return { onIndexChange, onNow, ...view };
}

describe("DynamicLayerTimeSlider 表示", () => {
  it("選んだコマの日付つきの時刻を上に出し、読み上げにも同じ時刻と位置を渡す", () => {
    renderSlider(1);
    expect(screen.getByText("9/24 10:00", { selector: "div" })).toBeInTheDocument();
    const ruler = screen.getByRole("slider", { name: "出発時刻" });
    expect(ruler).toHaveAttribute("aria-valuetext", "9/24 10:00");
    expect(ruler).toHaveAttribute("aria-valuenow", "1");
    expect(ruler).toHaveAttribute("aria-valuemax", "2");
  });

  it("目盛りはコマごとに1つ。正時は印を付けて広く取り、目盛りの文字はあるコマだけ", () => {
    renderSlider(0);
    const ticks = [...screen.getByRole("slider", { name: "出発時刻" }).firstElementChild!.children] as HTMLElement[];
    expect(ticks.map((tick) => tick.dataset.hour)).toEqual([undefined, "true", "true"]);
    expect(ticks.map((tick) => tick.textContent)).toEqual(["55", "10:00", ""]);
    expect(parseFloat(ticks[1].style.width)).toBeGreaterThan(parseFloat(ticks[0].style.width));
  });
});

describe("DynamicLayerTimeSlider 操作", () => {
  it("‹・›で1コマずつ動かし、端ではそれ以上動かせない", async () => {
    const first = renderSlider(0);
    expect(screen.getByRole("button", { name: "出発時刻を1つ前へ" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "出発時刻を1つ次へ" }));
    expect(first.onIndexChange).toHaveBeenCalledWith(1);
    first.unmount();

    const last = renderSlider(2);
    expect(screen.getByRole("button", { name: "出発時刻を1つ次へ" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "出発時刻を1つ前へ" }));
    expect(last.onIndexChange).toHaveBeenCalledWith(1);
  });

  it("矢印キーで1コマ、Home・Endで端へ動かす。もう動けない向きと他のキーでは何もしない", async () => {
    const { onIndexChange } = renderSlider(1);
    act(() => screen.getByRole("slider", { name: "出発時刻" }).focus());
    for (const key of ["{ArrowRight}", "{ArrowLeft}", "{Home}", "{End}", "{Enter}"]) await userEvent.keyboard(key);
    expect(onIndexChange.mock.calls.map(([index]) => index)).toEqual([2, 0, 0, 2]);
  });

  it("端では、その向きのキーは報告しない", async () => {
    const { onIndexChange } = renderSlider(0);
    act(() => screen.getByRole("slider", { name: "出発時刻" }).focus());
    await userEvent.keyboard("{ArrowLeft}{Home}");
    expect(onIndexChange).not.toHaveBeenCalled();
  });

  it("「現在」は、今のコマを見ていない間だけ押せ、押すと親へ知らせる", async () => {
    const away = renderSlider(2, 0);
    await userEvent.click(screen.getByRole("button", { name: "出発時刻を現在に戻す" }));
    expect(away.onNow).toHaveBeenCalled();
    away.unmount();

    renderSlider(0, 0);
    expect(screen.getByRole("button", { name: "出発時刻を現在に戻す" })).toBeDisabled();
  });
});

describe("DynamicLayerTimeSlider ルーラーとのつなぎ", () => {
  it("開いた時は、選んでいるコマへすぐに合わせる", () => {
    renderSlider(1);
    expect(embla.scrollTo).toHaveBeenCalledWith(1, true);
  });

  it("ルーラーが別のコマを選んだら親へ知らせ、同じコマのままなら知らせない", () => {
    const { onIndexChange } = renderSlider(0);
    act(() => embla.select(0));
    expect(onIndexChange).not.toHaveBeenCalled();
    act(() => embla.select(2));
    expect(onIndexChange).toHaveBeenCalledWith(2);
  });

  it("外から位置が変わったときだけルーラーを動かす（自分が知らせた位置へは動かし直さない）", () => {
    const { rerender, onIndexChange } = renderSlider(0);
    embla.scrollTo.mockClear();
    act(() => embla.select(2));
    const props = { frames: FRAMES, onIndexChange, currentIndex: 0, onNow: vi.fn(), ariaLabel: "出発時刻" };
    rerender(<DynamicLayerTimeSlider {...props} index={2} />);
    expect(embla.scrollTo).not.toHaveBeenCalled();
    rerender(<DynamicLayerTimeSlider {...props} index={0} />);
    expect(embla.scrollTo).toHaveBeenCalledWith(0, false);
  });
});

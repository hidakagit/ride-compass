import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { cardinalLabel } from "@/features/conditions/cardinalLabel";

import WindBearingSlider from "./WindBearingSlider";

function renderDial(value: number) {
  const onChange = vi.fn();
  render(<WindBearingSlider value={value} onChange={onChange} ariaLabel="走行方位" />);
  const dial = screen.getByRole("slider", { name: "走行方位" });
  // 画面上の位置: 左上(0,0)・幅68pxの円。中心は(34,34)。
  vi.spyOn(dial, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 68, height: 68 } as DOMRect);
  return { dial, onChange };
}

describe("WindBearingSlider 表示", () => {
  it("値（整数へ丸めた度）と方位の呼び名を、読み上げと文字の両方で出し、矢印をその向きへ回す", () => {
    const { dial } = renderDial(44.6);
    expect(dial).toHaveAttribute("aria-valuenow", "45");
    expect(dial).toHaveAttribute("aria-valuetext", `45度（${cardinalLabel(44.6)}）`);
    expect(screen.getByText(`45° ${cardinalLabel(44.6)}`)).toBeInTheDocument();
    expect((dial.firstElementChild as HTMLElement).style.transform).toBe("rotate(44.6deg)");
  });
});

describe("WindBearingSlider キー操作", () => {
  it("右・上で5度増やし、左・下で5度減らす。一周をまたいだら0〜360の中へ畳む", async () => {
    for (const [value, key, next] of [
      [10, "{ArrowRight}", 15],
      [10, "{ArrowUp}", 15],
      [10, "{ArrowLeft}", 5],
      [10, "{ArrowDown}", 5],
      [2, "{ArrowLeft}", 357],
      [358, "{ArrowRight}", 3],
    ] as const) {
      const { dial, onChange } = renderDial(value);
      act(() => dial.focus());
      await userEvent.keyboard(key);
      expect(onChange).toHaveBeenLastCalledWith(next);
      document.body.innerHTML = "";
    }
  });

  it("矢印以外のキーでは何もしない", async () => {
    const { dial, onChange } = renderDial(10);
    act(() => dial.focus());
    await userEvent.keyboard("{Enter}");
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("WindBearingSlider ドラッグ", () => {
  it("押した点の、中心から見た向きを値にする（北が0で時計回り）", () => {
    for (const [x, y, deg] of [
      [34, 0, 0],
      [68, 34, 90],
      [34, 68, 180],
      [0, 34, 270],
    ] as const) {
      const { dial, onChange } = renderDial(0);
      fireEvent.pointerDown(dial, { clientX: x, clientY: y });
      expect(onChange).toHaveBeenLastCalledWith(deg);
      act(() => {
        window.dispatchEvent(new MouseEvent("pointerup"));
      });
      document.body.innerHTML = "";
    }
  });

  it("押したまま動かすと追いかけ、指を離したら止まる", () => {
    const { dial, onChange } = renderDial(0);
    fireEvent.pointerDown(dial, { clientX: 34, clientY: 0 });
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 68, clientY: 34 }));
    });
    expect(onChange).toHaveBeenLastCalledWith(90);
    act(() => {
      window.dispatchEvent(new MouseEvent("pointerup"));
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 34, clientY: 68 }));
    });
    expect(onChange).toHaveBeenLastCalledWith(90);
  });

  it("中心そのものを押しても、値は数として読める向きになる", () => {
    const { dial, onChange } = renderDial(0);
    fireEvent.pointerDown(dial, { clientX: 34, clientY: 34 });
    expect(Number.isFinite(onChange.mock.lastCall![0])).toBe(true);
  });
});

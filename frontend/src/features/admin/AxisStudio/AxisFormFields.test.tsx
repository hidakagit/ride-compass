/**
 * `AxisFormFields.tsx`——軸スタジオの節が共有する入力部品: 材料が選ばれていないときの説明の口と、スライダーと数値欄の組。
 *
 * ここで見ないもの:
 * - 見出しと説明の口・材料の説明の口の中身（受け取った値を説明の部品へ詰め替えて渡すだけ） → 使う側の節
 * - 説明の開閉そのもの → `components/ui/InfoPopover`
 * - 数値欄の途中の文字の扱いと、数値欄から渡す値 → `components/ui/NumberInput`
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MaterialInfoButton, SliderNumberField } from "./AxisFormFields";

describe("MaterialInfoButton", () => {
  it("材料が選ばれていなければ、何も出さない", () => {
    const { container } = render(<MaterialInfoButton option={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("SliderNumberField", () => {
  function renderField(value: number, onChange = vi.fn()) {
    render(<SliderNumberField label="係数" value={value} onChange={onChange} min={-10} max={10} step={0.1} />);
    return {
      slider: screen.getByRole("slider", { name: "係数(スライダー)" }),
      number: screen.getByRole("spinbutton", { name: "係数" }),
      onChange,
    };
  }

  it("数値欄は範囲の外の値もそのまま出す", () => {
    const { number } = renderField(25);
    expect(number).toHaveValue(25);
  });

  it("スライダーで動かした値を数で渡す", () => {
    const { slider, onChange } = renderField(1);
    fireEvent.change(slider, { target: { value: "-3.5" } });
    expect(onChange).toHaveBeenLastCalledWith(-3.5);
  });
});

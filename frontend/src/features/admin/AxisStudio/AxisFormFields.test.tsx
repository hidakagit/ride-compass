/**
 * `AxisFormFields.tsx`——軸スタジオの節が共有する入力部品: 材料の説明の口、見出しと説明、スライダーと数値欄の組。
 *
 * ここで見ないもの:
 * - 説明の開閉そのもの → `components/ui/InfoPopover`
 * - 数値欄の途中の文字の扱い → `components/ui/NumberInput`
 */
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MaterialInfoButton, SectionLabel, SliderNumberField } from "./AxisFormFields";

describe("MaterialInfoButton", () => {
  it("選んだ材料の説明を、材料の名前つきの口から開ける", async () => {
    render(
      <MaterialInfoButton
        option={{ id: "m", label: "材料A - m", name: "材料A", description: "材料Aの説明", dtype: "numeric", unit: "" }}
      />,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: /材料A - mの説明/ }));
    expect(await screen.findByText("材料Aの説明")).toBeInTheDocument();
  });

  it("材料が選ばれていなければ、何も出さない", () => {
    const { container } = render(<MaterialInfoButton option={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("SectionLabel", () => {
  it("説明があれば見出しの横に説明の口を置き、無ければ見出しだけ", () => {
    const { unmount } = render(<SectionLabel label="折れ点" description="説明文" />);
    expect(screen.getByText("折れ点")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /折れ点の説明/ })).toBeInTheDocument();
    unmount();

    render(<SectionLabel label="折れ点" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
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

  it("スライダーでも数値欄でも、動かした値を渡す", async () => {
    const { slider, number, onChange } = renderField(1);

    fireEvent.change(slider, { target: { value: "-3.5" } });
    expect(onChange).toHaveBeenLastCalledWith(-3.5);

    const user = userEvent.setup();
    await user.clear(number);
    await user.type(number, "12");
    expect(onChange).toHaveBeenLastCalledWith(12);
  });
});

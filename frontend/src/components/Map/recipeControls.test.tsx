import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AdjustmentStepper, FieldLabel, LevelPicker } from "./recipeControls";

// T113でCarStressRecipePanel専用に実装した3部品を、2つ目のレシピ（安全度レシピ）
// 登場を機に汎用化した（改善計画: 安全度レシピ）。切り出し自体で挙動が変わっていないことを
// ここで単体検証する（CarStressRecipePanel.test.tsx/SafetyRecipePanel.test.tsxは
// 呼び出し元経由の結合テストのため、部品単体の境界値はここでカバーする）。

describe("LevelPicker", () => {
  const levels = [1, 2, 3, 4];
  const colors = { 1: "#111111", 2: "#222222", 3: "#333333", 4: "#444444" };

  it("levelsぶんのボタンを表示し、選択値以下をdata-filled=trueにする", () => {
    render(<LevelPicker levels={levels} colors={colors} value={2} onChange={vi.fn()} groupLabel="テスト軸" />);

    const group = screen.getByRole("group", { name: "テスト軸" });
    expect(group).toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(4);
    expect(buttons[0]).toHaveAttribute("data-filled", "true"); // 1 <= 2
    expect(buttons[1]).toHaveAttribute("data-filled", "true"); // 2 <= 2
    expect(buttons[2]).toHaveAttribute("data-filled", "false"); // 3 > 2
    expect(buttons[3]).toHaveAttribute("data-filled", "false"); // 4 > 2
  });

  it("段階ボタンを押すとonChangeにその段階の値が渡る", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<LevelPicker levels={levels} colors={colors} value={1} onChange={onChange} groupLabel="テスト軸" />);

    await user.click(screen.getByRole("button", { name: "3" }));

    expect(onChange).toHaveBeenCalledWith(3);
  });

  it("選択中の段階はaria-pressed=trueを持つ", () => {
    render(<LevelPicker levels={levels} colors={colors} value={3} onChange={vi.fn()} groupLabel="テスト軸" />);

    expect(screen.getByRole("button", { name: "3" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "1" })).toHaveAttribute("aria-pressed", "false");
  });
});

describe("AdjustmentStepper", () => {
  it("-ボタンで値が1減り、+ボタンで値が1増える", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <AdjustmentStepper label="補正値" value={0} onChange={onChange} negativeColor="#00ff00" positiveColor="#ff0000" />,
    );

    await user.click(screen.getByRole("button", { name: "補正値を1減らす" }));
    expect(onChange).toHaveBeenLastCalledWith(-1);

    await user.click(screen.getByRole("button", { name: "補正値を1増やす" }));
    expect(onChange).toHaveBeenLastCalledWith(1);
  });

  it("数値入力欄への直接入力でも値が変わる", () => {
    const onChange = vi.fn();
    render(
      <AdjustmentStepper label="補正値" value={0} onChange={onChange} negativeColor="#00ff00" positiveColor="#ff0000" />,
    );

    const input = screen.getByRole("spinbutton", { name: "補正値" });
    fireEvent.change(input, { target: { value: "5" } });

    expect(onChange).toHaveBeenCalledWith(5);
  });

  it("入力欄を空にするとonChangeが0で呼ばれる(type=numberはブラウザ側で非数値文字を受け付けないため、空文字列がNumber()で0になる経路)", () => {
    const onChange = vi.fn();
    render(
      <AdjustmentStepper label="補正値" value={3} onChange={onChange} negativeColor="#00ff00" positiveColor="#ff0000" />,
    );

    const input = screen.getByRole("spinbutton", { name: "補正値" });
    fireEvent.change(input, { target: { value: "" } });

    expect(onChange).toHaveBeenCalledWith(0);
  });
});

describe("FieldLabel", () => {
  it("open=falseのときaria-expanded=falseで「表示」ラベルを持つ", () => {
    render(<FieldLabel label="項目" open={false} onToggle={vi.fn()} />);

    const button = screen.getByRole("button", { name: "項目の説明を表示" });
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("open=trueのときaria-expanded=trueで「隠す」ラベルを持つ", () => {
    render(<FieldLabel label="項目" open={true} onToggle={vi.fn()} />);

    const button = screen.getByRole("button", { name: "項目の説明を隠す" });
    expect(button).toHaveAttribute("aria-expanded", "true");
  });

  it("ボタンを押すとonToggleが呼ばれる", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(<FieldLabel label="項目" open={false} onToggle={onToggle} />);

    await user.click(screen.getByRole("button", { name: "項目の説明を表示" }));

    expect(onToggle).toHaveBeenCalledOnce();
  });
});

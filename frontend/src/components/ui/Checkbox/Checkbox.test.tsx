/**
 * `components/ui/Checkbox/Checkbox.tsx`——チェックボックス。
 *
 * 見るもの: 渡した状態の表示（`aria-checked`）・押したときに渡る次の状態・名前。
 *
 * ここで見ないもの: キーボードでの切り替え——Radix Checkboxの振る舞い。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Checkbox } from "./Checkbox";

describe("Checkbox", () => {
  it.each([
    [false, true],
    [true, false],
  ])("入っている状態が%sのとき、押すと%sが渡る", async (checked, next) => {
    const onCheckedChange = vi.fn();
    render(<Checkbox checked={checked} onCheckedChange={onCheckedChange} aria-label="研究モード" />);

    const checkbox = screen.getByRole("checkbox", { name: "研究モード" });
    expect(checkbox).toHaveAttribute("aria-checked", String(checked));

    await userEvent.click(checkbox);

    expect(onCheckedChange).toHaveBeenCalledWith(next);
  });
});

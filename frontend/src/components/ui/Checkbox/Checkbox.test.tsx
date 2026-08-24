import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Checkbox } from "./Checkbox";

describe("Checkbox", () => {
  it("checkboxロールで描画され、既定は未チェック", () => {
    render(<Checkbox aria-label="同意する" />);
    const box = screen.getByRole("checkbox", { name: "同意する" });
    expect(box).toHaveAttribute("aria-checked", "false");
  });

  it("checked=trueならchecked状態になる", () => {
    render(<Checkbox aria-label="同意する" checked onCheckedChange={() => {}} />);
    expect(screen.getByRole("checkbox", { name: "同意する" })).toHaveAttribute("aria-checked", "true");
  });

  it("クリックするとonCheckedChangeがtrueで呼ばれる", async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<Checkbox aria-label="同意する" checked={false} onCheckedChange={onCheckedChange} />);

    await user.click(screen.getByRole("checkbox", { name: "同意する" }));

    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it("disabled指定時はクリックしてもonCheckedChangeが呼ばれない", async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<Checkbox aria-label="同意する" disabled onCheckedChange={onCheckedChange} />);

    await user.click(screen.getByRole("checkbox", { name: "同意する" }));

    expect(onCheckedChange).not.toHaveBeenCalled();
  });
});

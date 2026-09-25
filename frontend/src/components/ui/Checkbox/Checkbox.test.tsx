import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Checkbox } from "./Checkbox";

describe("Checkbox", () => {
  it("クリックするとonCheckedChangeがtrueで呼ばれる", async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<Checkbox aria-label="同意する" checked={false} onCheckedChange={onCheckedChange} />);

    await user.click(screen.getByRole("checkbox", { name: "同意する" }));

    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });
});

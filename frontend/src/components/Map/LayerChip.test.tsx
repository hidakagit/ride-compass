import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LayerChip from "./LayerChip";

describe("LayerChip", () => {
  it("押すとonClickが呼ばれる", async () => {
    const onClick = vi.fn();
    render(<LayerChip label="路面" on={false} onClick={onClick} />);

    screen.getByRole("button", { name: "路面" }).click();

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("ON/OFFはaria-pressedで伝える（見た目の色だけに頼らない）", () => {
    const { rerender } = render(<LayerChip label="路面" on={false} onClick={vi.fn()} />);
    expect(screen.getByRole("button", { name: "路面" })).toHaveAttribute("aria-pressed", "false");

    rerender(<LayerChip label="路面" on onClick={vi.fn()} />);
    expect(screen.getByRole("button", { name: "路面" })).toHaveAttribute("aria-pressed", "true");
  });

  it("ariaLabelを渡すとそちらを読み上げ名にする（略名のチップ向け）", () => {
    render(<LayerChip label="路面" on={false} ariaLabel="路面の種類" onClick={vi.fn()} />);

    expect(screen.getByRole("button", { name: "路面の種類" })).toBeInTheDocument();
  });
});

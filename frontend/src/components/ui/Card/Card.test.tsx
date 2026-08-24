import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Card } from "./Card";

describe("Card", () => {
  it("子要素をそのまま描画する", () => {
    render(<Card>中身</Card>);
    expect(screen.getByText("中身")).toBeInTheDocument();
  });

  it("背景・角丸・paddingの既定クラスを持つ", () => {
    render(<Card>中身</Card>);
    const card = screen.getByText("中身");
    expect(card.className).toContain("bg-[var(--color-surface-2)]");
    expect(card.className).toContain("rounded-md");
  });

  it("classNameを渡すと合成される", () => {
    render(<Card className="mt-4">中身</Card>);
    expect(screen.getByText("中身").className).toContain("mt-4");
  });
});

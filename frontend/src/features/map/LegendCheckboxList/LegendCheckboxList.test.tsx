import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import LegendCheckboxList from "./LegendCheckboxList";

const LEGEND = [
  { key: "a", label: "舗装", color: "#111111", filter: [] },
  { key: "b", label: "大きい点", color: "#222222", filter: [], diameterPx: 12 },
  { key: "other", label: "不明・他", color: "#333333", filter: [], isFallback: true },
];

function renderList(props: Partial<Parameters<typeof LegendCheckboxList>[0]> = {}) {
  const onToggle = vi.fn();
  render(
    <LegendCheckboxList
      legend={LEGEND}
      hiddenKeys={["b"]}
      onToggle={onToggle}
      listClassName="list"
      rowClassName="row"
      swatchClassName="swatch"
      {...props}
    />,
  );
  return onToggle;
}

describe("LegendCheckboxList（凡例のチェック一覧）", () => {
  it("隠していない行にチェックが付き、押すとその行の鍵で切り替えを頼む", async () => {
    const onToggle = renderList();
    expect(screen.getByRole("checkbox", { name: "舗装" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "大きい点" })).not.toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "大きい点" }));
    expect(onToggle).toHaveBeenCalledWith("b");
  });

  it("色見本は行の色で、大きさで意味を示す行だけ地図の点と同じ大きさにする", () => {
    renderList();
    const [plain, sized] = [screen.getByText("舗装"), screen.getByText("大きい点")].map(
      (row) => row.querySelector(".swatch") as HTMLElement,
    );
    expect(plain).toHaveStyle({ background: "#111111" });
    expect(plain.style.width).toBe("");
    expect(sized).toHaveStyle({ background: "#222222", width: "12px", height: "12px" });
  });

  it("受け皿の行は、呼び出し側が見た目を渡したときだけ区別する", () => {
    renderList({ rowFallbackClassName: "fallback" });
    expect(screen.getByText("不明・他")).toHaveClass("row", "fallback");
    expect(screen.getByText("舗装")).not.toHaveClass("fallback");
  });
});

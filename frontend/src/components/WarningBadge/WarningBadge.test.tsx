import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import WarningBadgeList, { type WarningBadgeItem } from "./WarningBadge";

describe("WarningBadgeList（改善計画T205）", () => {
  it("itemsが空の場合は何も描画しない", () => {
    const { container } = render(<WarningBadgeList items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("itemsぶんのバッジをlabelで表示する", () => {
    const items: WarningBadgeItem[] = [
      { id: "14", label: "雷注意報", level: "advisory" },
      { id: "43", label: "大雨危険警報", level: "warning" },
    ];
    render(<WarningBadgeList items={items} />);

    expect(screen.getByText("雷注意報")).toBeInTheDocument();
    expect(screen.getByText("大雨危険警報")).toBeInTheDocument();
  });

  it("levelに応じたクラス名（advisory/warning/emergency_warning）を付与する", () => {
    const items: WarningBadgeItem[] = [
      { id: "10", label: "大雨注意報", level: "advisory" },
      { id: "03", label: "大雨警報", level: "warning" },
      { id: "33", label: "大雨特別警報", level: "emergency_warning" },
    ];
    render(<WarningBadgeList items={items} />);

    expect(screen.getByText("大雨注意報").className).toMatch(/advisory/);
    expect(screen.getByText("大雨警報").className).toMatch(/warning/);
    expect(screen.getByText("大雨特別警報").className).toMatch(/emergency_warning/);
  });

  it("titleを渡した場合はホバー用の補足として設定される", () => {
    const items: WarningBadgeItem[] = [{ id: "14", label: "雷注意報", level: "advisory", title: "付随事項: 竜巻" }];
    render(<WarningBadgeList items={items} />);

    expect(screen.getByText("雷注意報")).toHaveAttribute("title", "付随事項: 竜巻");
  });

  it("role=listでアクセシビリティツリー上まとまりを表す", () => {
    const items: WarningBadgeItem[] = [{ id: "14", label: "雷注意報", level: "advisory" }];
    render(<WarningBadgeList items={items} />);

    expect(screen.getByRole("list", { name: "気象警報・注意報" })).toBeInTheDocument();
    expect(screen.getByRole("listitem")).toHaveTextContent("雷注意報");
  });
});

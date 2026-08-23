import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import WarningBadgeList, { type WarningBadgeItem } from "./WarningBadge";

// UI改善（2026-08-24）: 天候ヘッダーが常に1行に収まるよう、常時表示は「最高警戒度+件数の
// サマリーボタン1個」のみへ変更した（以前は警報・注意報の全件を常時バッジとして並べており、
// 件数によってヘッダーが2行以上に折り返る問題があった）。個々の警報の内訳・補足（title）は
// サマリーボタンを押して開くPopover内でのみ見える。

describe("WarningBadgeList（改善計画T205、UI改善2026-08-24でサマリーボタン化）", () => {
  it("itemsが空の場合は何も描画しない", () => {
    const { container } = render(<WarningBadgeList items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("1件のときはそのレベルの名称だけをボタンに表示する", () => {
    const items: WarningBadgeItem[] = [{ id: "14", label: "雷注意報", level: "advisory" }];
    render(<WarningBadgeList items={items} />);

    const button = screen.getByRole("button", { name: /気象警報・注意報あり: 注意報/ });
    expect(button).toHaveTextContent("注意報");
    expect(button.className).toMatch(/advisory/);
    // 個々のitemのlabelは開く前は見えない。
    expect(screen.queryByText("雷注意報")).not.toBeInTheDocument();
  });

  it("複数件のときは最も警戒度が高いレベル+件数をボタンに表示する（advisoryとwarningが混在→warning側）", () => {
    const items: WarningBadgeItem[] = [
      { id: "14", label: "雷注意報", level: "advisory" },
      { id: "43", label: "大雨危険警報", level: "warning" },
    ];
    render(<WarningBadgeList items={items} />);

    const button = screen.getByRole("button", { name: /気象警報・注意報あり: 警報2件/ });
    expect(button).toHaveTextContent("警報2件");
    expect(button.className).toMatch(/warning/);
  });

  it("severe_warning（厳重警戒）が混在すると厳重警戒側が選ばれる", () => {
    const items: WarningBadgeItem[] = [
      { id: "10", label: "大雨注意報", level: "advisory" },
      { id: "wbgt", label: "厳重警戒", level: "severe_warning" },
    ];
    render(<WarningBadgeList items={items} />);
    expect(screen.getByRole("button", { name: /厳重警戒2件/ })).toBeInTheDocument();
  });

  it("emergency_warning（特別警報）が混在すると特別警報側が選ばれる", () => {
    const items: WarningBadgeItem[] = [
      { id: "10", label: "大雨注意報", level: "advisory" },
      { id: "33", label: "大雨特別警報", level: "emergency_warning" },
    ];
    render(<WarningBadgeList items={items} />);
    expect(screen.getByRole("button", { name: /特別警報2件/ })).toBeInTheDocument();
  });

  it("ボタンを押すと全件の詳細（label・補足）がPopoverで見える", async () => {
    const user = userEvent.setup();
    const items: WarningBadgeItem[] = [
      { id: "14", label: "雷注意報", level: "advisory", title: "付随事項: 竜巻" },
      { id: "43", label: "大雨危険警報", level: "warning" },
    ];
    render(<WarningBadgeList items={items} />);

    await user.click(screen.getByRole("button", { name: /気象警報・注意報あり/ }));

    expect(screen.getByRole("list", { name: "気象警報・注意報の詳細" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("雷注意報")).toBeInTheDocument();
    expect(screen.getByText("雷注意報").className).toMatch(/advisory/);
    expect(screen.getByText("付随事項: 竜巻")).toBeInTheDocument();
    expect(screen.getByText("大雨危険警報")).toBeInTheDocument();
    expect(screen.getByText("大雨危険警報").className).toMatch(/warning/);
  });
});

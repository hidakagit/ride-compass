import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { LegendEntry } from "./legendFilter";
import LegendCheckboxList from "./LegendCheckboxList";

// 改善計画T525: MapLayersPanel.tsx: renderLegendCheckboxesとRouteAxisProfile.tsxの
// 凡例チェックボックス重複を統合したコンポーネント。widthの有無によるスウォッチ/
// WidthSwatchの出し分け・isFallback行への追加classの付与を検証する。
describe("LegendCheckboxList", () => {
  const LEGEND: LegendEntry[] = [
    { key: "asphalt", label: "アスファルト", color: "#111", filter: [] },
    { key: "unknown", label: "不明・他", color: "#999", filter: [], isFallback: true },
  ];

  it("凡例ごとにチェックボックスを描画し、hiddenKeysに含まれる項目は未チェックにする", () => {
    render(
      <LegendCheckboxList
        legend={LEGEND}
        hiddenKeys={["unknown"]}
        onToggle={vi.fn()}
        listClassName="list"
        rowClassName="row"
        swatchClassName="swatch"
      />
    );
    expect(screen.getByRole("checkbox", { name: "アスファルト" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "不明・他" })).not.toBeChecked();
  });

  it("チェックボックスをクリックするとそのentryのkeyでonToggleを呼ぶ", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <LegendCheckboxList
        legend={LEGEND}
        hiddenKeys={[]}
        onToggle={onToggle}
        listClassName="list"
        rowClassName="row"
        swatchClassName="swatch"
      />
    );
    await user.click(screen.getByRole("checkbox", { name: "アスファルト" }));
    expect(onToggle).toHaveBeenCalledWith("asphalt");
  });

  it("rowFallbackClassNameを指定すると、isFallback行のみrowClassNameへ追加classを付与する", () => {
    render(
      <LegendCheckboxList
        legend={LEGEND}
        hiddenKeys={[]}
        onToggle={vi.fn()}
        listClassName="list"
        rowClassName="row"
        rowFallbackClassName="rowFallback"
        swatchClassName="swatch"
      />
    );
    const normalRow = screen.getByRole("checkbox", { name: "アスファルト" }).closest("label");
    const fallbackRow = screen.getByRole("checkbox", { name: "不明・他" }).closest("label");
    expect(normalRow?.className).toBe("row");
    expect(fallbackRow?.className).toBe("row rowFallback");
  });

  it("widthを持つentryは色スウォッチではなくWidthSwatch（太さバー）を描く", () => {
    const legendWithWidth: LegendEntry[] = [
      { key: "residential", label: "生活道路", color: "#333", filter: [], width: 2 },
    ];
    const { container } = render(
      <LegendCheckboxList
        legend={legendWithWidth}
        hiddenKeys={[]}
        onToggle={vi.fn()}
        listClassName="list"
        rowClassName="row"
        swatchClassName="swatch"
      />
    );
    expect(container.querySelector(".swatch")).not.toBeInTheDocument();
    expect(screen.getByText("生活道路").parentElement?.querySelector('[class*="bar"]')).toBeInTheDocument();
  });
});

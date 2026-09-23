import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import HardFilterPanel, { DEFAULT_HARD_FILTERS } from "./HardFilterPanel";

// 除外の種類・名前・既定はbackendの宣言（生成物）が決める。テストはその一覧を母集団にする。
const FILTERS = routeGenerateConfig.hard_filters.filters;

function renderPanel(hardFilters: Record<string, boolean>) {
  const onHardFiltersChange = vi.fn();
  render(<HardFilterPanel hardFilters={hardFilters} onHardFiltersChange={onHardFiltersChange} />);
  return onHardFiltersChange;
}

describe("HardFilterPanel", () => {
  it("種類ごとに1つの切り替えを出し、保存された選択が無い種類は既定の状態で出す", () => {
    renderPanel({});
    expect(FILTERS).not.toHaveLength(0);
    for (const { key, label } of FILTERS) {
      const chip = screen.getByRole("button", { name: `${label}を除外` });
      expect(chip).toHaveAttribute("aria-pressed", String(DEFAULT_HARD_FILTERS[key]));
    }
  });

  it("押すとその種類だけを反転して親へ渡す（他の種類の選択は保つ）", async () => {
    const [first, ...rest] = FILTERS;
    const current = Object.fromEntries(rest.map(({ key }) => [key, true]));
    const onChange = renderPanel(current);
    await userEvent.click(screen.getByRole("button", { name: `${first.label}を除外` }));
    expect(onChange).toHaveBeenCalledWith({ ...current, [first.key]: !DEFAULT_HARD_FILTERS[first.key] });
  });

  it("既定と違う選択があるときだけ「既定値に戻す」を出し、押すと既定へ戻す", async () => {
    renderPanel({ ...DEFAULT_HARD_FILTERS });
    expect(screen.queryByRole("button", { name: "除外を既定値に戻す" })).not.toBeInTheDocument();

    const [first] = FILTERS;
    const onChange = renderPanel({ ...DEFAULT_HARD_FILTERS, [first.key]: !DEFAULT_HARD_FILTERS[first.key] });
    await userEvent.click(screen.getByRole("button", { name: "除外を既定値に戻す" }));
    expect(onChange).toHaveBeenCalledWith(DEFAULT_HARD_FILTERS);
  });
});

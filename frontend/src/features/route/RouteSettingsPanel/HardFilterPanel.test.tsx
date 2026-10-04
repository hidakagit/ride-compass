/**
 * `RouteSettingsPanel/HardFilterPanel.tsx`——「除外」タブ。除外できる道路の種類ごとの切り替えと、既定へ戻す操作。
 *
 * 見るもの: 種類ごとに名前の付いた切り替えを並べ、押すとその種類だけを反転した値を上げること、既定と違う間だけ
 * 既定へ戻す操作を出すこと、(i)の奥の説明。
 *
 * ここで見ないもの: 保存値を今の項目へ揃えること → `features/route/useGenerationConditions.test.ts`（このパネルは
 * 全項目の揃った値を受け取る）。生成の要求へ載せること → `features/route/useRouteGeneration.test.ts`。
 *
 * 種類・名前・既定は生成物（`route-generate-config.json`）から読み、テストに書き写さない。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { HardFilterOverride } from "@/types/route";

import HardFilterPanel, { DEFAULT_HARD_FILTERS } from "./HardFilterPanel";

const FILTERS = routeGenerateConfig.hard_filters.filters;
const [FIRST] = FILTERS;

function renderPanel(hardFilters: HardFilterOverride) {
  const onHardFiltersChange = vi.fn();
  render(<HardFilterPanel hardFilters={hardFilters} onHardFiltersChange={onHardFiltersChange} />);
  return onHardFiltersChange;
}

/** 最初の種類だけを既定から反転した値。 */
const CUSTOMIZED: HardFilterOverride = { ...DEFAULT_HARD_FILTERS, [FIRST.key]: !DEFAULT_HARD_FILTERS[FIRST.key] };

describe("HardFilterPanel", () => {
  it("生成物の種類ごとに、名前の付いた切り替えを受け取った値の押下状態で並べる", () => {
    renderPanel(CUSTOMIZED);

    for (const { key, label } of FILTERS) {
      expect(screen.getByRole("button", { name: `${label}を除外` })).toHaveAttribute(
        "aria-pressed",
        String(CUSTOMIZED[key]),
      );
    }
  });

  it("押すとその種類だけを反転した値を上げる", async () => {
    const onHardFiltersChange = renderPanel(DEFAULT_HARD_FILTERS);

    await userEvent.click(screen.getByRole("button", { name: `${FIRST.label}を除外` }));

    expect(onHardFiltersChange).toHaveBeenCalledExactlyOnceWith(CUSTOMIZED);
  });

  it("既定と違う種類があるときだけ既定へ戻す操作を出し、押すと既定を上げる", async () => {
    renderPanel(DEFAULT_HARD_FILTERS);
    expect(screen.queryByRole("button", { name: "除外を既定値に戻す" })).not.toBeInTheDocument();

    const onHardFiltersChange = renderPanel(CUSTOMIZED);
    await userEvent.click(screen.getByRole("button", { name: "除外を既定値に戻す" }));

    expect(onHardFiltersChange).toHaveBeenCalledExactlyOnceWith(DEFAULT_HARD_FILTERS);
  });

  it("(i)の奥に、外した種類は経路から完全に外れることを置く", async () => {
    renderPanel(DEFAULT_HARD_FILTERS);

    await userEvent.click(screen.getByRole("button", { name: "除外する道路の説明を表示" }));

    expect(screen.getByText(/ONにした種類は経路から完全に外れます/)).toBeInTheDocument();
  });
});

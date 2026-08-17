import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_TRAFFIC_STRESS_RECIPE } from "@/components/Map/trafficStressExpression";
import TrafficStressRecipePanel from "./TrafficStressRecipePanel";

// base_by_highwayのエントリ数（domain/traffic.py: TRAFFIC_STRESS_BASE_BY_HIGHWAY由来）
// ＋スカラーフィールド12個ぶんの入力欄が出る。エントリ数はテスト実行時のフィクスチャ
// （traffic-stress-recipe.json）依存にせず、DEFAULT_TRAFFIC_STRESS_RECIPE自体から数える。
const HIGHWAY_COUNT = Object.keys(DEFAULT_TRAFFIC_STRESS_RECIPE.base_by_highway).length;
const SCALAR_FIELD_COUNT = 12;

describe("TrafficStressRecipePanel", () => {
  it("上書き無効時は数値入力欄を表示しない", () => {
    render(
      <TrafficStressRecipePanel
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_TRAFFIC_STRESS_RECIPE}
        onRecipeChange={vi.fn()}
      />,
    );

    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("上書き有効時はhighway別基準値+スカラー12項目の入力欄を表示する", () => {
    render(
      <TrafficStressRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_TRAFFIC_STRESS_RECIPE}
        onRecipeChange={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("spinbutton")).toHaveLength(HIGHWAY_COUNT + SCALAR_FIELD_COUNT);
  });

  it("トグルをクリックするとonOverrideEnabledChangeが呼ばれる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <TrafficStressRecipePanel
        overrideEnabled={false}
        onOverrideEnabledChange={onChange}
        recipe={DEFAULT_TRAFFIC_STRESS_RECIPE}
        onRecipeChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("checkbox"));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("highway別基準値の入力を変更するとbase_by_highwayだけが更新されたレシピで呼ばれる", () => {
    const onRecipeChange = vi.fn();
    render(
      <TrafficStressRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_TRAFFIC_STRESS_RECIPE}
        onRecipeChange={onRecipeChange}
      />,
    );

    const primaryRow = screen.getByText("primary", { selector: "td" }).closest("tr");
    if (!primaryRow) throw new Error("primary行が見つかりません");
    const primaryInput = within(primaryRow).getByRole("spinbutton");
    fireEvent.change(primaryInput, { target: { value: "2" } });

    expect(onRecipeChange).toHaveBeenCalledWith({
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      base_by_highway: { ...DEFAULT_TRAFFIC_STRESS_RECIPE.base_by_highway, primary: 2 },
    });
  });

  it("既定値に戻すボタンでonRecipeChangeがDEFAULT_TRAFFIC_STRESS_RECIPEで呼ばれる", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    const customRecipe = { ...DEFAULT_TRAFFIC_STRESS_RECIPE, cycleway_track_adjustment: -1 };
    render(
      <TrafficStressRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={customRecipe}
        onRecipeChange={onRecipeChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "既定値に戻す" }));

    expect(onRecipeChange).toHaveBeenCalledWith(DEFAULT_TRAFFIC_STRESS_RECIPE);
  });
});

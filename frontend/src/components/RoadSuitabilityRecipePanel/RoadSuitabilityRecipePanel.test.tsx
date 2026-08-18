import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_ROAD_SUITABILITY_RECIPE } from "@/components/Map/trafficStressExpression";
import RoadSuitabilityRecipePanel from "./RoadSuitabilityRecipePanel";

// 旧TrafficStressRecipePanel.test.tsxのhighway別基準値・cycleway補正に関するテストを
// そのまま移設した(改善計画: 車との近さ材料の共有元化)。

const HIGHWAY_COUNT = Object.keys(DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway).length;
const CYCLEWAY_FIELD_COUNT = 3;

function renderPanel(overrides: Partial<React.ComponentProps<typeof RoadSuitabilityRecipePanel>> = {}) {
  return render(
    <RoadSuitabilityRecipePanel
      overrideEnabled={true}
      onOverrideEnabledChange={vi.fn()}
      recipe={DEFAULT_ROAD_SUITABILITY_RECIPE}
      onRecipeChange={vi.fn()}
      {...overrides}
    />,
  );
}

describe("RoadSuitabilityRecipePanel", () => {
  it("上書き無効時は入力欄を表示しない", () => {
    renderPanel({ overrideEnabled: false });

    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /の基準値$/ })).not.toBeInTheDocument();
  });

  it("上書き有効時はcycleway3項目の入力欄+highway別のレベルピッカーを表示する", () => {
    renderPanel();

    expect(screen.getAllByRole("spinbutton")).toHaveLength(CYCLEWAY_FIELD_COUNT);
    expect(screen.getAllByRole("group", { name: /の基準値$/ })).toHaveLength(HIGHWAY_COUNT);
  });

  it("トグルをクリックするとonOverrideEnabledChangeが呼ばれる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderPanel({ overrideEnabled: false, onOverrideEnabledChange: onChange });

    await user.click(screen.getByRole("checkbox"));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("highway別基準値のレベルピッカーを押すとbase_by_highwayだけが更新されたレシピで呼ばれる", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    renderPanel({ onRecipeChange });

    const primaryInfoButton = screen.getByRole("button", { name: "国道クラスの幹線道路の説明を表示" });
    const primaryRow = primaryInfoButton.closest("tr");
    if (!primaryRow) throw new Error("primary行が見つかりません");
    const primaryPicker = within(primaryRow).getByRole("group");
    await user.click(within(primaryPicker).getByRole("button", { name: "2" }));

    expect(onRecipeChange).toHaveBeenCalledWith({
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      base_by_highway: { ...DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway, primary: 2 },
    });
  });

  it("補正値のステッパーの-/+ボタンで値が1ずつ増減する", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    renderPanel({ onRecipeChange });

    // 既定のcycleway_track_adjustmentは-2。
    await user.click(screen.getByRole("button", { name: "専用レーンの補正を1減らす" }));
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      cycleway_track_adjustment: -3,
    });

    await user.click(screen.getByRole("button", { name: "専用レーンの補正を1増やす" }));
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      cycleway_track_adjustment: -1,
    });
  });

  it("情報アイコンをクリックすると説明が表示され、もう一度押すと隠れる", async () => {
    const user = userEvent.setup();
    renderPanel();

    const infoButton = screen.getByRole("button", { name: "専用レーンの補正の説明を表示" });
    expect(
      screen.queryByText("cycleway=track（車道と分離された自転車専用レーン）に該当する道路への補正値"),
    ).not.toBeInTheDocument();

    await user.click(infoButton);
    expect(
      screen.getByText("cycleway=track（車道と分離された自転車専用レーン）に該当する道路への補正値"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "専用レーンの補正の説明を隠す" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "専用レーンの補正の説明を隠す" }));
    expect(
      screen.queryByText("cycleway=track（車道と分離された自転車専用レーン）に該当する道路への補正値"),
    ).not.toBeInTheDocument();
  });

  it("既定値に戻すボタンでonRecipeChangeがDEFAULT_ROAD_SUITABILITY_RECIPEで呼ばれる", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    const customRecipe = { ...DEFAULT_ROAD_SUITABILITY_RECIPE, cycleway_track_adjustment: -1 };
    renderPanel({ recipe: customRecipe, onRecipeChange });

    await user.click(screen.getByRole("button", { name: "既定値に戻す" }));

    expect(onRecipeChange).toHaveBeenCalledWith(DEFAULT_ROAD_SUITABILITY_RECIPE);
  });
});

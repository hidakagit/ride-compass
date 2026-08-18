import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_SAFETY_RECIPE } from "@/components/Map/safetyExpression";
import { DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE, DEFAULT_ROAD_SUITABILITY_RECIPE } from "@/components/Map/trafficStressExpression";
import SafetyRecipePanel from "./SafetyRecipePanel";

// TrafficStressRecipePanel.test.tsxと同じ構成・観点(改善計画: 車との近さ材料の共有元化)。
// 車との近さ材料の共有元化以降、このパネルは街灯・トンネル補正(G,H)の1グループのみを
// 持つ薄いパネルになった。highway別基準値・cycleway・制限速度・車線数(多い方)・指定路線は
// RoadSuitabilityRecipePanel/MotorVehicleDensityRecipePanelへ移設済みで、このパネルには
// 読み取り専用の参照セクション(CarClosenessReferenceSection)としてのみ現れる。

function renderPanel(overrides: Partial<React.ComponentProps<typeof SafetyRecipePanel>> = {}) {
  return render(
    <SafetyRecipePanel
      overrideEnabled={true}
      onOverrideEnabledChange={vi.fn()}
      recipe={DEFAULT_SAFETY_RECIPE}
      onRecipeChange={vi.fn()}
      roadSuitabilityRecipe={DEFAULT_ROAD_SUITABILITY_RECIPE}
      motorVehicleDensityRecipe={DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE}
      {...overrides}
    />,
  );
}

describe("SafetyRecipePanel", () => {
  it("上書き無効時は数値入力欄も参照セクションも表示しない", () => {
    renderPanel({ overrideEnabled: false });

    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(screen.queryByText(/土台: 道路適正＋自動車密度/)).not.toBeInTheDocument();
  });

  it("上書き有効時は街灯・トンネル補正2項目の入力欄を表示する", () => {
    renderPanel();

    expect(screen.getAllByRole("spinbutton")).toHaveLength(2);
  });

  it("トグルをクリックするとonOverrideEnabledChangeが呼ばれる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderPanel({ overrideEnabled: false, onOverrideEnabledChange: onChange });

    await user.click(screen.getByRole("checkbox"));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("街灯・トンネル補正のステッパーの-/+ボタンで値が1ずつ増減する", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    renderPanel({ onRecipeChange });

    // 既定のlit_adjustmentは-1。
    await user.click(screen.getByRole("button", { name: "街灯ありの補正を1減らす" }));
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_SAFETY_RECIPE,
      lit_adjustment: -2,
    });

    await user.click(screen.getByRole("button", { name: "街灯ありの補正を1増やす" }));
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_SAFETY_RECIPE,
      lit_adjustment: 0,
    });
  });

  it("情報アイコンをクリックすると説明が表示され、もう一度押すと隠れる", async () => {
    const user = userEvent.setup();
    renderPanel();

    const infoButton = screen.getByRole("button", { name: "トンネルの補正の説明を表示" });
    expect(screen.queryByText("tunnel=yes（トンネル区間）に該当する道路への補正値")).not.toBeInTheDocument();

    await user.click(infoButton);
    expect(screen.getByText("tunnel=yes（トンネル区間）に該当する道路への補正値")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "トンネルの補正の説明を隠す" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "トンネルの補正の説明を隠す" }));
    expect(screen.queryByText("tunnel=yes（トンネル区間）に該当する道路への補正値")).not.toBeInTheDocument();
  });

  it("既定値に戻すボタンでonRecipeChangeがDEFAULT_SAFETY_RECIPEで呼ばれる", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    const customRecipe = { ...DEFAULT_SAFETY_RECIPE, lit_adjustment: -3 };
    renderPanel({ recipe: customRecipe, onRecipeChange });

    await user.click(screen.getByRole("button", { name: "既定値に戻す" }));

    expect(onRecipeChange).toHaveBeenCalledWith(DEFAULT_SAFETY_RECIPE);
  });

  it("参照セクションに道路適正・自動車密度の現在値を読み取り専用で表示する", () => {
    const customMotorVehicleDensity = {
      ...DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
      designation_adjustment: -4,
    };
    renderPanel({ motorVehicleDensityRecipe: customMotorVehicleDensity });

    expect(screen.getByText(/土台: 道路適正＋自動車密度/)).toBeInTheDocument();
    expect(screen.getByText(/指定路線: -4/)).toBeInTheDocument();
    expect(within(screen.getByText(/指定路線: -4/).closest("ul")!).queryByRole("spinbutton")).not.toBeInTheDocument();
  });
});

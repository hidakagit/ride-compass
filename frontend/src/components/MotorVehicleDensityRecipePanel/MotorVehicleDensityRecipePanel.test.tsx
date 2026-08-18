import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE } from "@/components/Map/carStressExpression";
import MotorVehicleDensityRecipePanel from "./MotorVehicleDensityRecipePanel";

// 旧CarStressRecipePanel.test.tsxの制限速度補正・車線数(多い方)補正・指定路線補正に
// 関するテストをそのまま移設した(改善計画: 車との近さ材料の共有元化)。

function renderPanel(overrides: Partial<React.ComponentProps<typeof MotorVehicleDensityRecipePanel>> = {}) {
  return render(
    <MotorVehicleDensityRecipePanel
      overrideEnabled={true}
      onOverrideEnabledChange={vi.fn()}
      recipe={DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE}
      onRecipeChange={vi.fn()}
      {...overrides}
    />,
  );
}

describe("MotorVehicleDensityRecipePanel", () => {
  it("上書き有効時は制限速度2対+車線数1対+指定路線1項目の入力欄を表示する", () => {
    renderPanel();

    // maxspeed(閾値+補正×2対=4) + lanes_high(閾値+補正×1対=2) + designation(補正のみ=1) = 7
    expect(screen.getAllByRole("spinbutton")).toHaveLength(7);
  });

  it("上書き無効でも既定値の入力欄を表示する", () => {
    renderPanel({ overrideEnabled: false });

    expect(screen.getAllByRole("spinbutton")).toHaveLength(7);
  });

  it("上書きチップをクリックするとonOverrideEnabledChangeが呼ばれる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderPanel({ overrideEnabled: false, onOverrideEnabledChange: onChange });

    await user.click(screen.getByRole("button", { name: "自動車密度のレシピを上書き" }));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("上書き無効時に入力欄を変更すると上書きが自動でONになる", () => {
    const onOverrideEnabledChange = vi.fn();
    const onRecipeChange = vi.fn();
    renderPanel({ overrideEnabled: false, onOverrideEnabledChange, onRecipeChange });

    const lowSpeedInfoButton = screen.getByRole("button", { name: "低速道路の説明を表示" });
    const lowSpeedRow = lowSpeedInfoButton.closest("div");
    if (!lowSpeedRow) throw new Error("低速道路の行が見つかりません");
    const [adjustmentInput] = within(lowSpeedRow).getAllByRole("spinbutton");

    fireEvent.change(adjustmentInput, { target: { value: "-3" } });

    expect(onOverrideEnabledChange).toHaveBeenCalledWith(true);
    expect(onRecipeChange).toHaveBeenCalled();
  });

  it("制限速度補正の閾値と補正値をそれぞれ変更すると対応するキーだけが更新される", () => {
    const onRecipeChange = vi.fn();
    renderPanel({ onRecipeChange });

    const lowSpeedInfoButton = screen.getByRole("button", { name: "低速道路の説明を表示" });
    const lowSpeedRow = lowSpeedInfoButton.closest("div");
    if (!lowSpeedRow) throw new Error("低速道路の行が見つかりません");
    const [adjustmentInput, thresholdInput] = within(lowSpeedRow).getAllByRole("spinbutton");

    fireEvent.change(thresholdInput, { target: { value: "25" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
      maxspeed_low_threshold: 25,
    });

    fireEvent.change(adjustmentInput, { target: { value: "-3" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
      maxspeed_low_adjustment: -3,
    });
  });

  it("車線数(多い方)補正の閾値と補正値をそれぞれ変更すると対応するキーだけが更新される", () => {
    const onRecipeChange = vi.fn();
    renderPanel({ onRecipeChange });

    const infoButton = screen.getByRole("button", { name: "多車線道路の説明を表示" });
    const row = infoButton.closest("div");
    if (!row) throw new Error("多車線道路の行が見つかりません");
    const [adjustmentInput, thresholdInput] = within(row).getAllByRole("spinbutton");

    fireEvent.change(thresholdInput, { target: { value: "5" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
      lanes_high_threshold: 5,
    });

    fireEvent.change(adjustmentInput, { target: { value: "2" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
      lanes_high_adjustment: 2,
    });
  });

  it("指定路線補正のステッパーの-/+ボタンで値が1ずつ増減する", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    renderPanel({ onRecipeChange });

    const base = DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE.designation_adjustment;
    await user.click(screen.getByRole("button", { name: "指定路線への補正を1減らす" }));
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
      designation_adjustment: base - 1,
    });

    await user.click(screen.getByRole("button", { name: "指定路線への補正を1増やす" }));
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
      designation_adjustment: base + 1,
    });
  });

  it("情報アイコンをクリックすると説明が表示され、もう一度押すと隠れる", async () => {
    const user = userEvent.setup();
    renderPanel();

    const infoButton = screen.getByRole("button", { name: "指定路線への補正の説明を表示" });
    expect(
      screen.queryByText("緊急輸送道路（N10）・重要物流道路（N12）のいずれかに該当する道路に加える補正値"),
    ).not.toBeInTheDocument();

    await user.click(infoButton);
    expect(
      screen.getByText("緊急輸送道路（N10）・重要物流道路（N12）のいずれかに該当する道路に加える補正値"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "指定路線への補正の説明を隠す" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "指定路線への補正の説明を隠す" }));
    expect(
      screen.queryByText("緊急輸送道路（N10）・重要物流道路（N12）のいずれかに該当する道路に加える補正値"),
    ).not.toBeInTheDocument();
  });

  it("既定値に戻すボタンでonRecipeChangeがDEFAULT_MOTOR_VEHICLE_DENSITY_RECIPEで呼ばれる", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    const customRecipe = { ...DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE, designation_adjustment: -3 };
    renderPanel({ recipe: customRecipe, onRecipeChange });

    await user.click(screen.getByRole("button", { name: "既定値に戻す" }));

    expect(onRecipeChange).toHaveBeenCalledWith(DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE);
  });
});

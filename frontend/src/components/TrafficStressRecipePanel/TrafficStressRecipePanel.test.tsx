import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_TRAFFIC_STRESS_RECIPE,
} from "@/components/Map/trafficStressExpression";
import TrafficStressRecipePanel from "./TrafficStressRecipePanel";

// 車との近さ材料の共有元化（改善計画）以降、このパネルは少車線道路(F)の1グループのみを
// 持つ薄いパネルになった。highway別基準値・cycleway・制限速度・車線数(多い方)・指定路線は
// RoadSuitabilityRecipePanel/MotorVehicleDensityRecipePanelへ移設済みで、このパネルには
// 読み取り専用の参照セクション（CarClosenessReferenceSection）としてのみ現れる。

function renderPanel(overrides: Partial<React.ComponentProps<typeof TrafficStressRecipePanel>> = {}) {
  return render(
    <TrafficStressRecipePanel
      overrideEnabled={true}
      onOverrideEnabledChange={vi.fn()}
      recipe={DEFAULT_TRAFFIC_STRESS_RECIPE}
      onRecipeChange={vi.fn()}
      roadSuitabilityRecipe={DEFAULT_ROAD_SUITABILITY_RECIPE}
      motorVehicleDensityRecipe={DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE}
      {...overrides}
    />,
  );
}

describe("TrafficStressRecipePanel", () => {
  it("上書き無効時は数値入力欄も参照セクションも表示しない", () => {
    renderPanel({ overrideEnabled: false });

    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(screen.queryByText(/土台: 道路適正＋自動車密度/)).not.toBeInTheDocument();
  });

  it("上書き有効時は少車線道路の閾値+補正値の入力欄を表示する", () => {
    renderPanel();

    // 少車線道路(lanes_low)は閾値+補正値の対フィールドが1組のみ(2 spinbutton)。
    expect(screen.getAllByRole("spinbutton")).toHaveLength(2);
  });

  it("トグルをクリックするとonOverrideEnabledChangeが呼ばれる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderPanel({ overrideEnabled: false, onOverrideEnabledChange: onChange });

    await user.click(screen.getByRole("checkbox"));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("少車線道路の閾値と補正値をそれぞれ変更すると対応するキーだけが更新される", () => {
    const onRecipeChange = vi.fn();
    renderPanel({ onRecipeChange });

    const infoButton = screen.getByRole("button", { name: "少車線道路の説明を表示" });
    const row = infoButton.closest("div");
    if (!row) throw new Error("少車線道路の行が見つかりません");
    const [adjustmentInput, thresholdInput] = within(row).getAllByRole("spinbutton");

    fireEvent.change(thresholdInput, { target: { value: "2" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      lanes_low_threshold: 2,
    });

    fireEvent.change(adjustmentInput, { target: { value: "-2" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      lanes_low_adjustment: -2,
    });
  });

  it("情報アイコンをクリックすると説明が表示され、もう一度押すと隠れる", async () => {
    const user = userEvent.setup();
    renderPanel();

    const infoButton = screen.getByRole("button", { name: "少車線道路の説明を表示" });
    expect(
      screen.queryByText(/車線数がこの値以下の道路を「少車線道路」とみなし/),
    ).not.toBeInTheDocument();

    await user.click(infoButton);
    expect(screen.getByText(/車線数がこの値以下の道路を「少車線道路」とみなし/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "少車線道路の説明を隠す" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "少車線道路の説明を隠す" }));
    expect(
      screen.queryByText(/車線数がこの値以下の道路を「少車線道路」とみなし/),
    ).not.toBeInTheDocument();
  });

  it("既定値に戻すボタンでonRecipeChangeがDEFAULT_TRAFFIC_STRESS_RECIPEで呼ばれる", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    const customRecipe = { ...DEFAULT_TRAFFIC_STRESS_RECIPE, lanes_low_adjustment: -3 };
    renderPanel({ recipe: customRecipe, onRecipeChange });

    await user.click(screen.getByRole("button", { name: "既定値に戻す" }));

    expect(onRecipeChange).toHaveBeenCalledWith(DEFAULT_TRAFFIC_STRESS_RECIPE);
  });

  it("参照セクションに道路適正・自動車密度の現在値を読み取り専用で表示する", () => {
    const customRoadSuitability = {
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      cycleway_track_adjustment: -5,
    };
    renderPanel({ roadSuitabilityRecipe: customRoadSuitability });

    expect(screen.getByText(/土台: 道路適正＋自動車密度/)).toBeInTheDocument();
    expect(screen.getByText(/専用レーン: -5/)).toBeInTheDocument();
    // 参照セクションは読み取り専用であり、入力欄は含まない。
    expect(within(screen.getByText(/専用レーン: -5/).closest("ul")!).queryByRole("spinbutton")).not.toBeInTheDocument();
  });
});

import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_SAFETY_RECIPE } from "@/components/Map/safetyExpression";
import SafetyRecipePanel from "./SafetyRecipePanel";

// TrafficStressRecipePanel.test.tsxと同じ構成・観点（改善計画: 安全度レシピ）。
// base_by_highwayのエントリ数（domain/safety.py: SAFETY_BASE_BY_HIGHWAY由来）＋スカラー
// フィールド12個ぶんの入力欄が出る。安全度はlanes_low（少車線）を持たず代わりにlit/tunnel
// の2補正を持つ（shoulderは実測0.0%の死に補正だったため改善計画T122で撤去）
// （cycleway3＋maxspeed2対×2＋lanes1対×2＋lit/tunnel2＋designation1＝12）。
const HIGHWAY_COUNT = Object.keys(DEFAULT_SAFETY_RECIPE.base_by_highway).length;
const SCALAR_FIELD_COUNT = 12;

describe("SafetyRecipePanel", () => {
  it("上書き無効時は数値入力欄を表示しない", () => {
    render(
      <SafetyRecipePanel
        overrideEnabled={false}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_SAFETY_RECIPE}
        onRecipeChange={vi.fn()}
      />,
    );

    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("上書き有効時はスカラー12項目の入力欄+highway別のレベルピッカーを表示する", () => {
    render(
      <SafetyRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_SAFETY_RECIPE}
        onRecipeChange={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("spinbutton")).toHaveLength(SCALAR_FIELD_COUNT);
    expect(screen.getAllByRole("group", { name: /の基準値$/ })).toHaveLength(HIGHWAY_COUNT);
  });

  it("トグルをクリックするとonOverrideEnabledChangeが呼ばれる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SafetyRecipePanel
        overrideEnabled={false}
        onOverrideEnabledChange={onChange}
        recipe={DEFAULT_SAFETY_RECIPE}
        onRecipeChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("checkbox"));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("highway別基準値のレベルピッカーを押すとbase_by_highwayだけが更新されたレシピで呼ばれる", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    render(
      <SafetyRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_SAFETY_RECIPE}
        onRecipeChange={onRecipeChange}
      />,
    );

    const primaryInfoButton = screen.getByRole("button", { name: "国道クラスの幹線道路の説明を表示" });
    const primaryRow = primaryInfoButton.closest("tr");
    if (!primaryRow) throw new Error("primary行が見つかりません");
    const primaryPicker = within(primaryRow).getByRole("group");
    await user.click(within(primaryPicker).getByRole("button", { name: "2" }));

    expect(onRecipeChange).toHaveBeenCalledWith({
      ...DEFAULT_SAFETY_RECIPE,
      base_by_highway: { ...DEFAULT_SAFETY_RECIPE.base_by_highway, primary: 2 },
    });
  });

  it("制限速度補正の閾値と補正値をそれぞれ変更すると対応するキーだけが更新される", () => {
    const onRecipeChange = vi.fn();
    render(
      <SafetyRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_SAFETY_RECIPE}
        onRecipeChange={onRecipeChange}
      />,
    );

    const lowSpeedInfoButton = screen.getByRole("button", { name: "低速道路の説明を表示" });
    const lowSpeedRow = lowSpeedInfoButton.closest("div");
    if (!lowSpeedRow) throw new Error("低速道路の行が見つかりません");
    const [adjustmentInput, thresholdInput] = within(lowSpeedRow).getAllByRole("spinbutton");

    fireEvent.change(thresholdInput, { target: { value: "25" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_SAFETY_RECIPE,
      maxspeed_low_threshold: 25,
    });

    fireEvent.change(adjustmentInput, { target: { value: "-3" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_SAFETY_RECIPE,
      maxspeed_low_adjustment: -3,
    });
  });

  it("街灯・トンネル補正のステッパーの-/+ボタンで値が1ずつ増減する", async () => {
    // 安全度のみが持つ補正（交通ストレスには無い、domain/safety.py: SafetyRecipe参照）。
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    render(
      <SafetyRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_SAFETY_RECIPE}
        onRecipeChange={onRecipeChange}
      />,
    );

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
    render(
      <SafetyRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_SAFETY_RECIPE}
        onRecipeChange={vi.fn()}
      />,
    );

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
    const customRecipe = { ...DEFAULT_SAFETY_RECIPE, cycleway_track_adjustment: -1 };
    render(
      <SafetyRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={customRecipe}
        onRecipeChange={onRecipeChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "既定値に戻す" }));

    expect(onRecipeChange).toHaveBeenCalledWith(DEFAULT_SAFETY_RECIPE);
  });
});

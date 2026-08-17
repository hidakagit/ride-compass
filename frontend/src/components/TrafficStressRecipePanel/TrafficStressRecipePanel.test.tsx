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

    // ラベルは日本語訳（改善計画: 研究タブの用語日本語化）。highway=primaryのラベルは
    // 「国道クラスの幹線道路」（情報アイコンのaria-labelを手がかりに行を特定する）。
    const primaryInfoButton = screen.getByRole("button", { name: "国道クラスの幹線道路の説明を表示" });
    const primaryRow = primaryInfoButton.closest("tr");
    if (!primaryRow) throw new Error("primary行が見つかりません");
    const primaryInput = within(primaryRow).getByRole("spinbutton");
    fireEvent.change(primaryInput, { target: { value: "2" } });

    expect(onRecipeChange).toHaveBeenCalledWith({
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      base_by_highway: { ...DEFAULT_TRAFFIC_STRESS_RECIPE.base_by_highway, primary: 2 },
    });
  });

  it("情報アイコンをクリックすると説明が表示され、もう一度押すと隠れる", async () => {
    // title属性のホバー表示はスマホのタップでは開かない（実機フィードバックで判明した
    // バグ）ため、クリック/タップで確実に開閉するボタンであることを検証する回帰テスト。
    const user = userEvent.setup();
    render(
      <TrafficStressRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_TRAFFIC_STRESS_RECIPE}
        onRecipeChange={vi.fn()}
      />,
    );

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

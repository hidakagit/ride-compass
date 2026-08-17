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

  it("上書き有効時はスカラー12項目の入力欄+highway別のレベルピッカーを表示する", () => {
    render(
      <TrafficStressRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_TRAFFIC_STRESS_RECIPE}
        onRecipeChange={vi.fn()}
      />,
    );

    // 基準値（改善計画: レシピ入力フォームの改善）は数値入力欄ではなくレベルピッカー
    // （role="group"、押しボタンの並び）になったため、spinbuttonはスカラー項目の
    // 12件（4対×2＋cycleway3＋designation1）のみになる。role="group"は<fieldset>にも
    // 暗黙的に付くため、レベルピッカーのaria-label（"○○の基準値"）で絞り込む。
    expect(screen.getAllByRole("spinbutton")).toHaveLength(SCALAR_FIELD_COUNT);
    expect(screen.getAllByRole("group", { name: /の基準値$/ })).toHaveLength(HIGHWAY_COUNT);
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

  it("highway別基準値のレベルピッカーを押すとbase_by_highwayだけが更新されたレシピで呼ばれる", async () => {
    // 基準値は改善計画: レシピ入力フォームの改善で数値入力欄からレベルピッカー
    // （低→高の押しボタン）へ変更された。
    const user = userEvent.setup();
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
    const primaryPicker = within(primaryRow).getByRole("group");
    await user.click(within(primaryPicker).getByRole("button", { name: "2" }));

    expect(onRecipeChange).toHaveBeenCalledWith({
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      base_by_highway: { ...DEFAULT_TRAFFIC_STRESS_RECIPE.base_by_highway, primary: 2 },
    });
  });

  it("制限速度補正の閾値と補正値をそれぞれ変更すると対応するキーだけが更新される", () => {
    // 改善計画: レシピ入力フォームの改善で、閾値+補正値が対で1行にまとまった
    // （ThresholdAdjustmentRow）。両方の入力欄が独立して正しいキーを更新することを確認する。
    const onRecipeChange = vi.fn();
    render(
      <TrafficStressRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_TRAFFIC_STRESS_RECIPE}
        onRecipeChange={onRecipeChange}
      />,
    );

    const lowSpeedInfoButton = screen.getByRole("button", { name: "低速道路の説明を表示" });
    // ラベル・ステッパー・条件（閾値）は同じ.field div内に横並びで入っている
    // （改善計画: レシピ入力フォームの改善、ThresholdAdjustmentRowのJSX参照）。
    const lowSpeedRow = lowSpeedInfoButton.closest("div");
    if (!lowSpeedRow) throw new Error("低速道路の行が見つかりません");
    // DOM順は補正値のステッパー入力欄が先、条件（閾値）の入力欄が後
    // （ThresholdAdjustmentRowのJSX順）。
    const [adjustmentInput, thresholdInput] = within(lowSpeedRow).getAllByRole("spinbutton");

    fireEvent.change(thresholdInput, { target: { value: "25" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      maxspeed_low_threshold: 25,
    });

    fireEvent.change(adjustmentInput, { target: { value: "-3" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      maxspeed_low_adjustment: -3,
    });
  });

  it("補正値のステッパーの-/+ボタンで値が1ずつ増減する", async () => {
    // 改善計画: レシピ入力フォームの改善で、0中心バー+数値入力から-/+ボタン付きの
    // ステッパーへ変更した（バーが視認できない・数値入力が入力しにくいという
    // フィードバックへの対応）。
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    render(
      <TrafficStressRecipePanel
        overrideEnabled={true}
        onOverrideEnabledChange={vi.fn()}
        recipe={DEFAULT_TRAFFIC_STRESS_RECIPE}
        onRecipeChange={onRecipeChange}
      />,
    );

    // 既定のcycleway_track_adjustmentは-2。
    await user.click(screen.getByRole("button", { name: "専用レーンの補正を1減らす" }));
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      cycleway_track_adjustment: -3,
    });

    await user.click(screen.getByRole("button", { name: "専用レーンの補正を1増やす" }));
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      cycleway_track_adjustment: -1,
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

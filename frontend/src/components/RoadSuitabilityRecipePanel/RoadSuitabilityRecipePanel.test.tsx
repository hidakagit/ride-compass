import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_ROAD_SUITABILITY_RECIPE } from "@/components/Map/carStressExpression";
import RoadSuitabilityRecipePanel from "./RoadSuitabilityRecipePanel";

// 旧CarStressRecipePanel.test.tsxのhighway別基準値・cycleway補正に関するテストを
// そのまま移設した(改善計画: 車との近さ材料の共有元化)。

const HIGHWAY_COUNT = Object.keys(DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway).length;
const CYCLEWAY_FIELD_COUNT = 3;

// RecipePanelSection・グループ（道路種別ごとの基準値/自転車インフラ補正）はいずれも
// Disclosure（Radix Accordion、T254）でデフォルト全閉。以前のネイティブ<details>時代は
// jsdomが閉じた中身も隠さずクエリ可能にする（実ブラウザとは異なる）挙動だったため、
// 各テストは開閉を意識せず中身の入力欄を直接検証できていたが、Radix化によりhidden属性で
// 実際に隠れるようになった（実ブラウザに忠実な挙動）。テストの意図（開閉状態そのものではなく
// 中身の挙動）を保つため、レンダー直後に全セクションを開く。
function openAllDisclosures() {
  // ネストしたDisclosure（RecipePanelSection内のグループ等）は外側を開いた直後の
  // querySelectorAllでは1回で全部拾いきれない場合があるため、変化が無くなるまで
  // 繰り返す（安全のため最大5周で打ち切る）。
  for (let i = 0; i < 5; i++) {
    // :not([aria-haspopup])でFieldLabelの情報Popover（Radix Popover.Trigger、
    // T253併用導入。同じくaria-expanded="false"を持つ）を除外し、Disclosure
    // （Accordion.Trigger）だけを対象にする。除外しないとテストのセットアップ自体が
    // 情報Popoverを開いてしまい、各テストが期待する「閉じた状態のPopoverボタン」を
    // 見つけられなくなる。
    const buttons = document.querySelectorAll('button[aria-expanded="false"]:not([aria-haspopup])');
    if (buttons.length === 0) break;
    buttons.forEach((button) => fireEvent.click(button));
  }
}

function renderPanel(overrides: Partial<React.ComponentProps<typeof RoadSuitabilityRecipePanel>> = {}) {
  const result = render(
    <RoadSuitabilityRecipePanel
      overrideEnabled={true}
      onOverrideEnabledChange={vi.fn()}
      recipe={DEFAULT_ROAD_SUITABILITY_RECIPE}
      onRecipeChange={vi.fn()}
      {...overrides}
    />,
  );
  openAllDisclosures();
  return result;
}

describe("RoadSuitabilityRecipePanel", () => {
  it("上書き有効時はcycleway3項目の入力欄+highway別のレベルピッカーを表示する", () => {
    renderPanel();

    expect(screen.getAllByRole("spinbutton")).toHaveLength(CYCLEWAY_FIELD_COUNT);
    expect(screen.getAllByRole("radiogroup", { name: /の基準値$/ })).toHaveLength(HIGHWAY_COUNT);
  });

  it("上書き無効でも既定値のレベルピッカーを表示する", () => {
    renderPanel({ overrideEnabled: false });

    expect(screen.getAllByRole("radiogroup", { name: /の基準値$/ })).toHaveLength(HIGHWAY_COUNT);
  });

  it("上書きチップをクリックするとonOverrideEnabledChangeが呼ばれる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderPanel({ overrideEnabled: false, onOverrideEnabledChange: onChange });

    await user.click(screen.getByRole("button", { name: "道路適正のレシピを上書き" }));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("上書き無効時にレベルピッカーを操作すると上書きが自動でONになる", async () => {
    const user = userEvent.setup();
    const onOverrideEnabledChange = vi.fn();
    const onRecipeChange = vi.fn();
    renderPanel({ overrideEnabled: false, onOverrideEnabledChange, onRecipeChange });

    const primaryInfoButton = screen.getByRole("button", { name: "国道クラスの幹線道路の説明を表示" });
    const primaryRow = primaryInfoButton.closest("tr");
    if (!primaryRow) throw new Error("primary行が見つかりません");
    const primaryPicker = within(primaryRow).getByRole("radiogroup");
    await user.click(within(primaryPicker).getByRole("radio", { name: "2" }));

    expect(onOverrideEnabledChange).toHaveBeenCalledWith(true);
    expect(onRecipeChange).toHaveBeenCalledWith({
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      base_by_highway: { ...DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway, primary: 2 },
    });
  });

  it("highway別基準値のレベルピッカーを押すとbase_by_highwayだけが更新されたレシピで呼ばれる", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    renderPanel({ onRecipeChange });

    const primaryInfoButton = screen.getByRole("button", { name: "国道クラスの幹線道路の説明を表示" });
    const primaryRow = primaryInfoButton.closest("tr");
    if (!primaryRow) throw new Error("primary行が見つかりません");
    const primaryPicker = within(primaryRow).getByRole("radiogroup");
    await user.click(within(primaryPicker).getByRole("radio", { name: "2" }));

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

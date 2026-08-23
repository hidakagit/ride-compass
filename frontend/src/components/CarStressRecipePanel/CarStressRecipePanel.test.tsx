import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_CAR_STRESS_RECIPE,
} from "@/components/Map/carStressExpression";
import CarStressRecipePanel from "./CarStressRecipePanel";

// 車との近さ材料の共有元化（改善計画）以降、このパネルは少車線道路(F)の1グループのみを
// 持つ薄いパネルになった。highway別基準値・cycleway・制限速度・車線数(多い方)・指定路線は
// RoadSuitabilityRecipePanel/MotorVehicleDensityRecipePanelへ移設済みで、このパネルには
// 読み取り専用の参照セクション（CarClosenessReferenceSection）としてのみ現れる。

// RecipePanelSection・内側のグループ（車線数補正）・CarClosenessReferenceSectionは
// いずれもDisclosure（Radix Accordion、T254）でデフォルト全閉。以前のネイティブ<details>
// 時代はjsdomが閉じた中身も隠さずクエリ可能にする（実ブラウザとは異なる）挙動だったため、
// 各テストは開閉を意識せず中身を直接検証できていたが、Radix化によりhidden属性で実際に
// 隠れるようになった（実ブラウザに忠実な挙動）。テストの意図（開閉状態そのものではなく
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

function renderPanel(overrides: Partial<React.ComponentProps<typeof CarStressRecipePanel>> = {}) {
  const result = render(
    <CarStressRecipePanel
      overrideEnabled={true}
      onOverrideEnabledChange={vi.fn()}
      recipe={DEFAULT_CAR_STRESS_RECIPE}
      onRecipeChange={vi.fn()}
      roadSuitabilityRecipe={DEFAULT_ROAD_SUITABILITY_RECIPE}
      motorVehicleDensityRecipe={DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE}
      {...overrides}
    />,
  );
  openAllDisclosures();
  return result;
}

describe("CarStressRecipePanel", () => {
  it("上書き有効時は少車線道路の閾値+補正値の入力欄を表示する", () => {
    renderPanel();

    // 少車線道路(lanes_low)は閾値+補正値の対フィールドが1組のみ(2 spinbutton)。
    expect(screen.getAllByRole("spinbutton")).toHaveLength(2);
  });

  it("上書き無効でも既定値の入力欄・参照セクションを表示する", () => {
    renderPanel({ overrideEnabled: false });

    expect(screen.getAllByRole("spinbutton")).toHaveLength(2);
    expect(screen.getByText(/土台: 道路適正＋自動車密度/)).toBeInTheDocument();
  });

  it("上書きチップをクリックするとonOverrideEnabledChangeが呼ばれる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderPanel({ overrideEnabled: false, onOverrideEnabledChange: onChange });

    await user.click(screen.getByRole("button", { name: "車の圧迫感のレシピを上書き" }));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("上書き無効時に入力欄を変更すると上書きが自動でONになる", () => {
    const onOverrideEnabledChange = vi.fn();
    const onRecipeChange = vi.fn();
    renderPanel({ overrideEnabled: false, onOverrideEnabledChange, onRecipeChange });

    const infoButton = screen.getByRole("button", { name: "少車線道路の説明を表示" });
    const row = infoButton.closest("div");
    if (!row) throw new Error("少車線道路の行が見つかりません");
    const [adjustmentInput] = within(row).getAllByRole("spinbutton");

    fireEvent.change(adjustmentInput, { target: { value: "-2" } });

    expect(onOverrideEnabledChange).toHaveBeenCalledWith(true);
    expect(onRecipeChange).toHaveBeenCalled();
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
      ...DEFAULT_CAR_STRESS_RECIPE,
      lanes_low_threshold: 2,
    });

    fireEvent.change(adjustmentInput, { target: { value: "-2" } });
    expect(onRecipeChange).toHaveBeenLastCalledWith({
      ...DEFAULT_CAR_STRESS_RECIPE,
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

  it("既定値に戻すボタンでonRecipeChangeがDEFAULT_CAR_STRESS_RECIPEで呼ばれる", async () => {
    const user = userEvent.setup();
    const onRecipeChange = vi.fn();
    const customRecipe = { ...DEFAULT_CAR_STRESS_RECIPE, lanes_low_adjustment: -3 };
    renderPanel({ recipe: customRecipe, onRecipeChange });

    await user.click(screen.getByRole("button", { name: "既定値に戻す" }));

    expect(onRecipeChange).toHaveBeenCalledWith(DEFAULT_CAR_STRESS_RECIPE);
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

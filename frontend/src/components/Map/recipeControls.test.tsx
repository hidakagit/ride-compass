import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FieldLabel } from "./recipeControls";

// T113でCarStressRecipePanel専用に実装した部品群を、2つ目のレシピ（当時の安全度レシピ。
// 安全度軸自体はT148で削除済み）登場を機に汎用化した（改善計画: 安全度レシピ）。
// 改善計画T292: 車ストレス専用の3レシピパネルの廃止に伴いLevelPicker/AdjustmentStepperは
// 削除された（recipeControls.tsx参照）。FieldLabelはWeightPanel/RouteSettingsPanelが
// 引き続き使うため単体検証を残す。

describe("FieldLabel", () => {
  it("初期状態はaria-expanded=falseで「表示」ラベルを持ち、説明文は表示しない", () => {
    render(<FieldLabel label="項目" description="項目の説明文" />);

    const button = screen.getByRole("button", { name: "項目の説明を表示" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("項目の説明文")).not.toBeInTheDocument();
  });

  it("ボタンを押すと説明文がフローティング表示され、ラベルが「隠す」に切り替わる", async () => {
    const user = userEvent.setup();
    render(<FieldLabel label="項目" description="項目の説明文" />);

    await user.click(screen.getByRole("button", { name: "項目の説明を表示" }));

    const button = screen.getByRole("button", { name: "項目の説明を隠す" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("項目の説明文")).toBeInTheDocument();
  });

  it("もう一度押すと閉じて「表示」ラベルへ戻る", async () => {
    const user = userEvent.setup();
    render(<FieldLabel label="項目" description="項目の説明文" />);

    await user.click(screen.getByRole("button", { name: "項目の説明を表示" }));
    await user.click(screen.getByRole("button", { name: "項目の説明を隠す" }));

    expect(screen.getByRole("button", { name: "項目の説明を表示" })).toHaveAttribute("aria-expanded", "false");
  });
});

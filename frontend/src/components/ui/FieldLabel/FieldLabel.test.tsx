import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FieldLabel } from "./FieldLabel";

describe("FieldLabel", () => {
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

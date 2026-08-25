import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { isResearchEnabled, setResearchEnabled } from "@/lib/researchMode";
import ResearchPanel from "./ResearchPanel";

describe("ResearchPanel", () => {
  beforeEach(() => {
    setResearchEnabled(false);
  });

  it("初期状態でチェックボックスのaria-checkedがisResearchEnabledと一致する", () => {
    render(<ResearchPanel />);
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toHaveAttribute("aria-checked", String(isResearchEnabled()));
    expect(checkbox).toHaveAttribute("aria-checked", "false");
  });

  it("チェックボックスをクリックするとsetResearchEnabled経由で状態が反映されaria-checkedが反転する", async () => {
    const user = userEvent.setup();
    render(<ResearchPanel />);
    const checkbox = screen.getByRole("checkbox");

    expect(checkbox).toHaveAttribute("aria-checked", "false");

    await act(async () => {
      await user.click(checkbox);
    });

    expect(checkbox).toHaveAttribute("aria-checked", "true");
    expect(isResearchEnabled()).toBe(true);
  });

  it("有効化はlocalStorageへ保存される（次回訪問時の復元用）", async () => {
    const user = userEvent.setup();
    render(<ResearchPanel />);

    await act(async () => {
      await user.click(screen.getByRole("checkbox"));
    });

    expect(window.localStorage.getItem("ridecompass:research-enabled")).toBe("1");
  });
});

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { isDebugEnabled, setDebugEnabled } from "@/lib/debugLog";
import DebugPanel from "./DebugPanel";

describe("DebugPanel", () => {
  beforeEach(() => {
    setDebugEnabled(false);
  });

  it("初期状態でチェックボックスのaria-checkedがisDebugEnabledと一致する", () => {
    render(<DebugPanel />);
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toHaveAttribute("aria-checked", String(isDebugEnabled()));
    expect(checkbox).toHaveAttribute("aria-checked", "false");
  });

  it("チェックボックスをクリックするとsetDebugEnabled経由で状態が反映されaria-checkedが反転する", async () => {
    const user = userEvent.setup();
    render(<DebugPanel />);
    const checkbox = screen.getByRole("checkbox");

    expect(checkbox).toHaveAttribute("aria-checked", "false");

    await act(async () => {
      await user.click(checkbox);
    });

    expect(checkbox).toHaveAttribute("aria-checked", "true");
    expect(isDebugEnabled()).toBe(true);
  });
});

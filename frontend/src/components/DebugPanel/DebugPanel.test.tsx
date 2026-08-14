import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { isDebugEnabled, setDebugEnabled } from "@/lib/debugLog";
import DebugPanel from "./DebugPanel";

describe("DebugPanel", () => {
  beforeEach(() => {
    setDebugEnabled(false);
  });

  it("初期状態でチェックボックスのcheckedがisDebugEnabledと一致する", () => {
    render(<DebugPanel />);
    const checkbox = screen.getByRole("checkbox") as HTMLInputElement;
    expect(checkbox.checked).toBe(isDebugEnabled());
    expect(checkbox.checked).toBe(false);
  });

  it("チェックボックスをクリックするとsetDebugEnabled経由で状態が反映されcheckedが反転する", async () => {
    const user = userEvent.setup();
    render(<DebugPanel />);
    const checkbox = screen.getByRole("checkbox") as HTMLInputElement;

    expect(checkbox.checked).toBe(false);

    await act(async () => {
      await user.click(checkbox);
    });

    expect(checkbox.checked).toBe(true);
    expect(isDebugEnabled()).toBe(true);
  });
});

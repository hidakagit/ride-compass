/**
 * `DebugPanel.tsx`——デバッグモードの今の値をチェックで示し、押すと切り替えること。
 *
 * ここで見ないもの:
 * - デバッグモードの保持・画面をまたぐ共有 → `lib/debugLog.ts`
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { isDebugEnabled, setDebugEnabled } from "@/lib/debugLog";

import DebugPanel from "./DebugPanel";

afterEach(() => {
  setDebugEnabled(false);
});

describe("DebugPanel", () => {
  it("今の値を示し、押すたびに入り切りする", async () => {
    setDebugEnabled(false);
    const user = userEvent.setup();
    render(<DebugPanel />);
    const checkbox = screen.getByRole("checkbox", { name: "デバッグログを表示" });
    expect(checkbox).not.toBeChecked();

    await user.click(checkbox);
    expect(isDebugEnabled()).toBe(true);
    expect(checkbox).toBeChecked();

    await user.click(checkbox);
    expect(isDebugEnabled()).toBe(false);
    expect(checkbox).not.toBeChecked();
  });
});

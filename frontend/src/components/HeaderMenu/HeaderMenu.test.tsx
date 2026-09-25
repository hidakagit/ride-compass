import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { isResearchEnabled, setResearchEnabled } from "@/lib/researchMode";
import HeaderMenu from "./HeaderMenu";

// 研究モードの切り替えは、公開ページのヘッダーのメニューから直接できる（管理画面を経由しない）。

function baseProps(overrides: Partial<Parameters<typeof HeaderMenu>[0]> = {}) {
  return {
    debugEnabled: false,
    debugConsoleOpen: false,
    onToggleDebugConsole: vi.fn(),
    ...overrides,
  };
}

describe("HeaderMenu", () => {
  beforeEach(() => {
    setResearchEnabled(false);
  });

  it("研究モードのチェックボックスは今の研究モードを映し、押すと研究モードを切り替える", async () => {
    const user = userEvent.setup();
    render(<HeaderMenu {...baseProps()} />);

    await user.click(screen.getByRole("button", { name: "メニュー" }));
    const checkbox = await screen.findByRole("checkbox", { name: /研究モード/ });
    expect(checkbox).toHaveAttribute("aria-checked", "false");
    await user.click(checkbox);

    expect(checkbox).toHaveAttribute("aria-checked", "true");
    expect(isResearchEnabled()).toBe(true);
  });

  it("debugEnabled=falseのときはデバッグログ項目を表示しない", async () => {
    const user = userEvent.setup();
    render(<HeaderMenu {...baseProps({ debugEnabled: false })} />);

    await user.click(screen.getByRole("button", { name: "メニュー" }));
    await screen.findByRole("checkbox", { name: /研究モード/ });

    expect(screen.queryByText("デバッグログを表示")).not.toBeInTheDocument();
  });

  it("debugEnabled=trueのときはデバッグログ項目を表示し、クリックでonToggleDebugConsoleが呼ばれる", async () => {
    const user = userEvent.setup();
    const onToggleDebugConsole = vi.fn();
    render(<HeaderMenu {...baseProps({ debugEnabled: true, onToggleDebugConsole })} />);

    await user.click(screen.getByRole("button", { name: "メニュー" }));
    const debugItem = await screen.findByText("デバッグログを表示");
    await user.click(debugItem);

    expect(onToggleDebugConsole).toHaveBeenCalledTimes(1);
  });

  it("debugConsoleOpen=trueのときは「デバッグログを隠す」表示になる", async () => {
    const user = userEvent.setup();
    render(<HeaderMenu {...baseProps({ debugEnabled: true, debugConsoleOpen: true })} />);

    await user.click(screen.getByRole("button", { name: "メニュー" }));

    expect(await screen.findByText("デバッグログを隠す")).toBeInTheDocument();
  });
});

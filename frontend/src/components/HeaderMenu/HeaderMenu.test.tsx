import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { isResearchEnabled, setResearchEnabled } from "@/lib/researchMode";
import HeaderMenu from "./HeaderMenu";

// 改善計画T519: 研究モードON/OFF・デバッグログ表示を1個のメニューアイコンへ集約した
// ヘッダーメニュー。以前はResearchPanel.tsx（/admin限定）が持っていたチェックボックス
// 操作のテストをここへ移設し、一般公開ページから`/admin`を経由せず研究モードを
// 切り替えられることを検証する。

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

  it("トリガーを押すとメニューが開き、研究モードのチェックボックスが現れる", async () => {
    const user = userEvent.setup();
    render(<HeaderMenu {...baseProps()} />);

    await user.click(screen.getByRole("button", { name: "メニュー" }));

    const checkbox = await screen.findByRole("checkbox", { name: /研究モード/ });
    expect(checkbox).toHaveAttribute("aria-checked", "false");
  });

  it("研究モードのチェックボックスをクリックすると、/adminを経由せずsetResearchEnabled経由で有効化される", async () => {
    const user = userEvent.setup();
    render(<HeaderMenu {...baseProps()} />);

    await user.click(screen.getByRole("button", { name: "メニュー" }));
    const checkbox = await screen.findByRole("checkbox", { name: /研究モード/ });
    await user.click(checkbox);

    expect(checkbox).toHaveAttribute("aria-checked", "true");
    expect(isResearchEnabled()).toBe(true);
    expect(window.localStorage.getItem("ridecompass:research-enabled")).toBe("1");
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

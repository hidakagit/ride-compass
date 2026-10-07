/**
 * `components/HeaderMenu/HeaderMenu.tsx`——ヘッダーのメニュー（使い方を見る・デバッグログの開閉）。
 *
 * 見るもの: メニューを開くと出る項目、「使い方を見る」を押すとメニューが閉じ、フォーカスが開くボタンへ戻ってから説明を見る状態に入る操作が上がること、
 * デバッグログの項目がデバッグモードの間だけ出て、開閉の状態を名前で出し、押すと開閉の操作が上がること。
 *
 * ここで見ないもの: デバッグモードそのもののON/OFF → `features/admin/DebugPanel/DebugPanel.tsx`（このメニューは呼び出し側から受け取るだけ）。
 * 説明を見る状態で部品の使い方が出ること → `components/UsageGuide/UsageGuide.test.tsx`（メニューのボタンの使い方の文は宣言）。
 * 押下の状態（`aria-pressed`）——`components/ui/Toggle`へそのまま渡すだけ。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import HeaderMenu from "./HeaderMenu";

async function openMenu(props: Partial<React.ComponentProps<typeof HeaderMenu>> = {}) {
  const onToggleDebugConsole = vi.fn();
  const onStartUsageGuide = vi.fn();
  render(
    <HeaderMenu
      debugEnabled={false}
      debugConsoleOpen={false}
      onToggleDebugConsole={onToggleDebugConsole}
      onStartUsageGuide={onStartUsageGuide}
      {...props}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "メニュー" }));
  return { onToggleDebugConsole, onStartUsageGuide };
}

describe("HeaderMenu", () => {
  it("「使い方を見る」を押すと、メニューが閉じてフォーカスが開くボタンへ戻ってから、説明を見る状態に入る操作が上がる", async () => {
    const { onStartUsageGuide } = await openMenu();
    let focusedAtStart: Element | null = null;
    onStartUsageGuide.mockImplementation(() => {
      focusedAtStart = document.activeElement;
    });

    await userEvent.click(screen.getByRole("button", { name: "使い方を見る" }));

    expect(onStartUsageGuide).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "使い方を見る" })).not.toBeInTheDocument();
    expect(focusedAtStart).toBe(screen.getByRole("button", { name: "メニュー" }));
  });

  describe("デバッグログ", () => {
    it("デバッグモードでなければ項目を出さない", async () => {
      await openMenu({ debugEnabled: false });

      expect(screen.queryByRole("button", { name: /デバッグログ/ })).not.toBeInTheDocument();
    });

    it.each([
      [false, "デバッグログを表示"],
      [true, "デバッグログを隠す"],
    ])("開いている（%s）かを、名前で出す", async (open, name) => {
      await openMenu({ debugEnabled: true, debugConsoleOpen: open });

      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    });

    it("押すと、開閉の操作が上がる", async () => {
      const { onToggleDebugConsole } = await openMenu({ debugEnabled: true });

      await userEvent.click(screen.getByRole("button", { name: "デバッグログを表示" }));

      expect(onToggleDebugConsole).toHaveBeenCalledTimes(1);
    });
  });
});

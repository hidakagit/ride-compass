/**
 * `components/HeaderMenu/HeaderMenu.tsx`——ヘッダーのメニュー（使い方を見る・研究モードの切り替え・デバッグログの開閉）。
 *
 * 見るもの: メニューを開くと出る項目、「使い方を見る」を押すとメニューが閉じて説明を見る状態に入る操作が上がること、
 * 研究モードのチェック（項目の文言を押しても）を押すと切り替わること、
 * デバッグログの項目がデバッグモードの間だけ出て、開閉の状態を名前で出し、押すと開閉の操作が上がること。
 *
 * ここで見ないもの: 研究モードの保存（`localStorage`）と、ほかの画面への知らせ → `lib/researchMode.ts`。
 * デバッグモードそのもののON/OFF → `features/admin/DebugPanel/DebugPanel.tsx`（このメニューは呼び出し側から受け取るだけ）。
 * 説明を見る状態で部品の使い方が出ること → `components/UsageGuide/UsageGuide.test.tsx`（メニューのボタンの使い方の文は宣言）。
 * 押したときに逆へ戻ること・押下の状態（`aria-pressed`）——`components/ui/Checkbox`・`components/ui/Toggle`へそのまま渡すだけ。
 *
 * 研究モードは本物の`lib/researchMode.ts`を通す。状態はモジュールが持つので、テストごとにOFFへ戻す。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setResearchEnabled } from "@/lib/researchMode";
import HeaderMenu from "./HeaderMenu";

const RESEARCH = "研究モード[実験スロット・比較・材料値]";

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

afterEach(() => {
  setResearchEnabled(false);
});

describe("HeaderMenu", () => {
  it("「使い方を見る」を押すと、メニューが閉じて説明を見る状態に入る操作が上がる", async () => {
    const { onStartUsageGuide } = await openMenu();

    await userEvent.click(screen.getByRole("button", { name: "使い方を見る" }));

    expect(onStartUsageGuide).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "使い方を見る" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: RESEARCH })).not.toBeInTheDocument();
  });

  describe("研究モード", () => {
    it("チェックを押すと切り替わる", async () => {
      await openMenu();
      const checkbox = screen.getByRole("checkbox", { name: RESEARCH });

      await userEvent.click(checkbox);

      expect(checkbox).toHaveAttribute("aria-checked", "true");
    });

    it("項目の文言を押しても切り替わる", async () => {
      await openMenu();

      await userEvent.click(screen.getByText(RESEARCH));

      expect(screen.getByRole("checkbox", { name: RESEARCH })).toHaveAttribute("aria-checked", "true");
    });
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

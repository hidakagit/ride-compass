/**
 * `components/HeaderMenu/HeaderMenu.tsx`——ヘッダーのメニュー（使い方を見る・デバッグログの開閉・バージョン表示）。
 *
 * 見るもの: メニューを開くと出る項目、「使い方を見る」を押すとメニューが閉じ、フォーカスが開くボタンへ戻ってから説明を見る状態に入る操作が上がること、
 * デバッグログの項目がデバッグモードの間だけ出て、開閉の状態を名前で出し、押すと開閉の操作が上がること、
 * 「バージョン表示」を押すと、フロントの版の口（`/api/version`）が返した版が窓に出ること。
 *
 * ここで見ないもの: デバッグモードそのもののON/OFF → `features/admin/DebugPanel/DebugPanel.tsx`（このメニューは呼び出し側から受け取るだけ）。
 * 説明を見る状態で部品の使い方が出ること → `components/UsageGuide/UsageGuide.test.tsx`（メニューのボタンの使い方の文は宣言）。
 * 押下の状態（`aria-pressed`）——`components/ui/Toggle`へそのまま渡すだけ。
 * 版をどこから読むか → `app/api/version/route.test.ts`。
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { FrontendVersion } from "@/services/versionApi";
import { onSameOrigin } from "@/testing/backendServer";

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

  describe("バージョン表示", () => {
    async function openVersion(version: FrontendVersion) {
      onSameOrigin("GET", "/api/version", () => Response.json(version));
      await openMenu();
      await userEvent.click(screen.getByRole("button", { name: "バージョン表示" }));
      return screen.findByRole("dialog", { name: "バージョン" });
    }

    it("版の口が返したコミットの頭8文字を出す", async () => {
      const dialog = await openVersion({
        commit: "9c2521ce0123456789abcdef0123456789abcdef",
        started_at: "2026-10-08T22:00:00Z",
      });

      expect(await within(dialog).findByText(/版/)).toHaveTextContent(/^版 9c2521ce$/);
    });

    it("手元で動いている版は、版の代わりにそう出す", async () => {
      const dialog = await openVersion({ commit: null, started_at: "2026-10-08T22:00:00Z" });

      expect(await within(dialog).findByText("手元で動いている版です（本番の版ではありません）。")).toBeInTheDocument();
    });
  });
});

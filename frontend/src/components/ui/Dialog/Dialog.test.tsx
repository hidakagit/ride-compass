/**
 * `components/ui/Dialog/Dialog.tsx`——見出しの付いたモーダルの枠。
 *
 * 見るもの: 見出しを名前に持つダイアログとして中身を出すこと、✕で閉じる操作が上がること。
 *
 * ここで見ないもの: 閉じている間は出さないこと・Escや外側の押下で閉じる・フォーカスを閉じ込める——Radix Dialogの振る舞い。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DialogContent, DialogRoot } from "./Dialog";

function renderDialog() {
  const onOpenChange = vi.fn();
  render(
    <DialogRoot open onOpenChange={onOpenChange}>
      <DialogContent title="軸を合成">中身の文</DialogContent>
    </DialogRoot>,
  );
  return onOpenChange;
}

describe("DialogContent", () => {
  it("見出しを名前に持つダイアログに中身を出す", () => {
    renderDialog();

    const dialog = screen.getByRole("dialog", { name: "軸を合成" });
    expect(dialog).toHaveTextContent("中身の文");
  });

  it("✕を押すと、閉じる操作が上がる", async () => {
    const onOpenChange = renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "閉じる" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

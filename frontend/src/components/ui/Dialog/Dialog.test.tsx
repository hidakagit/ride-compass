/**
 * `components/ui/Dialog/Dialog.tsx`——見出しの付いたモーダルの枠と、消す前の確認の窓。
 *
 * 見るもの: 見出しを名前に持つダイアログとして中身を出すこと、✕で閉じる操作が上がること。
 * 確認の窓は、確かめるボタンでだけ確かめた知らせが上がり、キャンセルでは取り消しの知らせだけが上がること。
 *
 * ここで見ないもの: 閉じている間は出さないこと・Escや外側の押下で閉じる・フォーカスを閉じ込める——Radix Dialogの振る舞い。
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog, DialogContent, DialogRoot } from "./Dialog";

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

describe("ConfirmDialog", () => {
  function renderConfirm() {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog open title="候補をすべて消します" confirmLabel="消す" onConfirm={onConfirm} onCancel={onCancel}>
        消した候補は元に戻せません。
      </ConfirmDialog>,
    );
    return { onConfirm, onCancel, dialog: screen.getByRole("dialog", { name: "候補をすべて消します" }) };
  }

  it("確かめるボタンを押すと、確かめた知らせだけが上がる", async () => {
    const { onConfirm, onCancel, dialog } = renderConfirm();
    expect(dialog).toHaveTextContent("消した候補は元に戻せません。");

    await userEvent.click(within(dialog).getByRole("button", { name: "消す" }));

    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it.each(["キャンセル", "閉じる"])("「%s」を押すと、取り消しの知らせだけが上がる", async (name) => {
    const { onConfirm, onCancel, dialog } = renderConfirm();

    await userEvent.click(within(dialog).getByRole("button", { name }));

    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

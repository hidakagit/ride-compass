"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

// 汎用モーダルダイアログ。FloatingPanel(react-rndでドラッグ移動)・BottomSheet
// (自前pointerイベントで高さドラッグ)はドラッグ/リサイズという専用の振る舞いを持つため
// Radix Dialogを使わない自前実装のままにしてある(docs/modules/frontend/frontend-design-system.md参照)。
// このDialogは新規の単純なモーダル要求(ドラッグ不要な確認ダイアログ等)向けの土台。
//
// titleを必須propsにすることでアクセシブルな名前を型で強制する(Disclosureと
// 同じ既存方針)。
// 重なり順はglobals.cssのスケール（--z-floating-panel）。BottomSheetより上、
// 情報ポップオーバー（--z-top-popover、Dialogの中から開く）より下。

export const DialogRoot = RadixDialog.Root;

interface DialogContentProps {
  title: string;
  children: React.ReactNode;
  className?: string;
}

export function DialogContent({ title, children, className }: DialogContentProps) {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-[var(--z-floating-panel)] bg-black/40" />
      <RadixDialog.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-[var(--z-floating-panel)] w-[min(90vw,28rem)] -translate-x-1/2 -translate-y-1/2",
          "rounded-md border border-[var(--color-border-strong)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-float)]",
          "text-[var(--foreground)]",
          className,
        )}
      >
        <RadixDialog.Title className="text-[length:var(--font-size-md)] font-semibold">{title}</RadixDialog.Title>
        <div className="mt-3">{children}</div>
        <RadixDialog.Close
          aria-label="閉じる"
          className="absolute right-3 top-3 rounded-sm text-[length:var(--font-size-md)] text-[var(--foreground)]"
        >
          ✕
        </RadixDialog.Close>
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** 確かめるボタンの文言（「消す」等）。 */
  confirmLabel: string;
  onConfirm: () => void;
  /** キャンセル・✕・Esc・外側の押下のどれで閉じても呼ばれる。 */
  onCancel: () => void;
  children: React.ReactNode;
}

// 消すなど取り消せない操作の前の確認の窓。確かめるボタンを押したときだけonConfirmを呼び、閉じるのは呼び出し側が
// openを下ろして行う。
export function ConfirmDialog({ open, title, confirmLabel, onConfirm, onCancel, children }: ConfirmDialogProps) {
  return (
    <DialogRoot
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent title={title}>
        <p className={textVariants({ variant: "hint" })}>{children}</p>
        <div className="mt-3 flex justify-end gap-2">
          <Button size="sm" onClick={onCancel}>
            キャンセル
          </Button>
          <Button variant="danger" size="sm" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </DialogRoot>
  );
}

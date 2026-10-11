"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button/Button";
import { ConfirmDialog } from "@/components/ui/Dialog/Dialog";
import { GuideText } from "@/components/ui/GuideText/GuideText";
import { DeleteSavedIcon } from "@/components/ui/icons/icons";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { textVariants } from "@/components/ui/Text/Text";

interface SavedListProps<T extends { name: string }> {
  items: T[];
  /** 保存したものの呼び名（「地点」「設定」）。空の案内と消す確認の文に入る。 */
  noun: string;
  /** 空のときに(i)の奥へ置く、保存の仕方。 */
  howToSave: string;
  /** 行の名前の欄（消す操作の前に置く）。 */
  renderMain: (item: T) => React.ReactNode;
  /** 名前の欄と消す操作の間に置く、行ごとの操作。 */
  renderActions?: (item: T) => React.ReactNode;
  onRemove: (item: T) => void;
}

// 「保存」タブの一覧（地点・設定）。名前で見分け、消すは確認の窓で「消す」を押すまで消さない——一覧の形と消し方を
// 1か所に持ち、地点と設定で違って見えないようにする。
export default function SavedList<T extends { name: string }>({
  items,
  noun,
  howToSave,
  renderMain,
  renderActions,
  onRemove,
}: SavedListProps<T>) {
  const [removing, setRemoving] = useState<T | null>(null);

  return (
    <>
      {items.length === 0 ? (
        <p className={textVariants({ variant: "hint" })}>
          {`保存した${noun}はまだありません。`}
          <InfoPopover triggerAriaLabel={`${noun}の保存の仕方`} triggerClassName="ml-1 align-middle">
            <GuideText text={howToSave} />
          </InfoPopover>
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((item) => (
            <li
              key={item.name}
              className="flex items-center gap-1 rounded-sm border border-[var(--color-border)] px-1.5 py-1"
            >
              {renderMain(item)}
              {renderActions?.(item)}
              <Button
                variant="ghost"
                size="panelIcon"
                aria-label={`「${item.name}」を消す`}
                aria-haspopup="dialog"
                aria-expanded={removing?.name === item.name}
                onClick={() => setRemoving(item)}
              >
                <DeleteSavedIcon size={18} />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={removing !== null}
        title={`「${removing?.name ?? ""}」を消します`}
        confirmLabel="消す"
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          if (removing === null) return;
          setRemoving(null);
          onRemove(removing);
        }}
      >
        {`消した${noun}は元に戻せません。`}
      </ConfirmDialog>
    </>
  );
}

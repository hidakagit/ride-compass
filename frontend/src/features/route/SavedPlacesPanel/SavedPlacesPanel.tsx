"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button/Button";
import { ConfirmDialog } from "@/components/ui/Dialog/Dialog";
import { GuideText } from "@/components/ui/GuideText/GuideText";
import { DeleteSavedIcon } from "@/components/ui/icons/icons";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import type { SavedPlace } from "@/features/route/savedPlaces";

interface SavedPlacesPanelProps {
  places: SavedPlace[];
  onRemove: (place: SavedPlace) => void;
}

// 「保存」タブの「地点」。保存した地点の一覧と消すだけを置く——保存と呼び出しは、地点を置く所（条件タブの地点の詳しく）が持つ。
// 一覧の行は名前と辺りで、どこに置くかを選ばせない（置く地点は、打つ欄を押した地点で決まる）。
export default function SavedPlacesPanel({ places, onRemove }: SavedPlacesPanelProps) {
  // 消すを押した地点。確認の窓で「消す」を押すまで消さない。
  const [removing, setRemoving] = useState<SavedPlace | null>(null);

  return (
    <div className="flex flex-col gap-3">
      {places.length === 0 ? (
        <p className={textVariants({ variant: "hint" })}>
          保存した地点はまだありません。
          <InfoPopover triggerAriaLabel="地点の保存の仕方" triggerClassName="ml-1 align-middle">
            <GuideText text="条件タブで地点を押し、「地点を保存」で保存します。地点の打つ欄を押すと、保存した地点から選べます。" />
          </InfoPopover>
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {places.map((place) => (
            <li
              key={place.name}
              className="flex items-center gap-1 rounded-sm border border-[var(--color-border)] px-1.5 py-1"
            >
              <span className="min-w-0 flex-auto [overflow-wrap:anywhere]">
                <span className="font-semibold">{place.name}</span>
                {place.area !== null && (
                  <span className={cn("ml-1.5", textVariants({ variant: "note" }))}>{place.area}</span>
                )}
              </span>
              <Button
                variant="ghost"
                size="panelIcon"
                aria-label={`「${place.name}」を消す`}
                aria-haspopup="dialog"
                aria-expanded={removing?.name === place.name}
                onClick={() => setRemoving(place)}
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
        消した地点は元に戻せません。
      </ConfirmDialog>
    </div>
  );
}

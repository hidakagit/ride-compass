"use client";

import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import SavedList from "@/features/route/SavedList/SavedList";
import type { SavedPlace } from "@/features/route/savedPlaces";

interface SavedPlacesPanelProps {
  places: SavedPlace[];
  onRemove: (place: SavedPlace) => void;
}

// 「保存」タブの「地点」。保存した地点の一覧と消すだけを置く——保存と呼び出しは、地点を置く所（条件タブの地点の詳しく）が持つ。
// 一覧の行は名前と辺りで、どこに置くかを選ばせない（置く地点は、打つ欄を押した地点で決まる）。
export default function SavedPlacesPanel({ places, onRemove }: SavedPlacesPanelProps) {
  return (
    <div className="flex flex-col gap-3">
      <SavedList
        items={places}
        noun="地点"
        howToSave="条件タブで地点を押し、「地点を保存」で保存します。地点の打つ欄を押すと、保存した地点から選べます。"
        renderMain={(place) => (
          <span className="min-w-0 flex-auto [overflow-wrap:anywhere]">
            <span className="font-semibold">{place.name}</span>
            {place.area !== null && (
              <span className={cn("ml-1.5", textVariants({ variant: "note" }))}>{place.area}</span>
            )}
          </span>
        )}
        onRemove={onRemove}
      />
    </div>
  );
}

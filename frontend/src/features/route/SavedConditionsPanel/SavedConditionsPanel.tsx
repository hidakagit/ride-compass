"use client";

import { useState } from "react";

import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { Button } from "@/components/ui/Button/Button";
import { Input } from "@/components/ui/Input/Input";
import { textVariants } from "@/components/ui/Text/Text";
import { savedConditionSummary, type SavedCondition } from "@/features/route/savedConditions";
import { cn } from "@/lib/cn";

interface SavedConditionsPanelProps {
  saved: SavedCondition[];
  /** 名前の欄に最初から入れておく仮の名前（いまの条件から作る）。 */
  suggestedName: string;
  onSave: (name: string) => void;
  onRecall: (entry: SavedCondition) => void;
  onRemove: (name: string) => void;
}

// 「ルート設定」区分の「保存」タブ。呼び出すと各タブの値と地図のピンが入れ替わり、生成はいつもの「ルート生成」で行う
// （入れ替えたあとに値を確かめたり少し変えたりできる）。
export default function SavedConditionsPanel({
  saved,
  suggestedName,
  onSave,
  onRecall,
  onRemove,
}: SavedConditionsPanelProps) {
  // 手で書き換えるまでは、いまの条件から作る仮の名前を出す（条件を変えると名前の案も変わる）。
  const [nameDraft, setNameDraft] = useState<string | null>(null);
  const name = nameDraft ?? suggestedName;
  const overwriting = saved.some((entry) => entry.name === (name.trim() || suggestedName));
  const [recalledName, setRecalledName] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-3">
      <form
        className="flex items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          onSave(name);
          setNameDraft(null);
        }}
      >
        <Input
          aria-label="保存する名前"
          className="min-w-0 flex-auto"
          value={name}
          onChange={(event) => setNameDraft(event.target.value)}
          data-usage="いまの条件に付ける名前です。そのまま保存もできます。"
        />
        <Button
          type="submit"
          size="sm"
          className="flex-none"
          usage="いまの条件・重み・除外を、この名前でこの端末に保存します。同じ名前があれば上書きします。"
        >
          {overwriting ? "上書き" : "保存"}
        </Button>
      </form>

      <div className="flex items-center gap-1">
        <p className={textVariants({ variant: "hint" })}>保存した条件</p>
        <InfoPopover triggerAriaLabel="保存した条件の説明">
          距離・地点・重み・除外を保存します。出発時刻・想定速度・走行方位と、作った候補は保存しません。呼び出して作り直すと、
          道路や天気が変わっていれば前と同じ候補になるとは限りません。保存先はこの端末のブラウザの中だけです。
        </InfoPopover>
      </div>
      {saved.length === 0 ? (
        <p className={textVariants({ variant: "hint" })}>まだありません。</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {saved.map((entry) => (
            <li key={entry.name} className="flex items-center rounded-sm border border-[var(--color-border)] pr-1">
              <Button
                variant="ghost"
                size="bare"
                className="flex min-w-0 flex-auto flex-col items-start rounded-sm px-1.5 py-1 text-left text-[var(--foreground)]"
                aria-label={`「${entry.name}」を呼び出す`}
                usage="この条件で各タブの値と地図の地点を入れ替えます。作るのはいつもの「ルート生成」です。"
                onClick={() => {
                  onRecall(entry);
                  setRecalledName(entry.name);
                }}
              >
                <span className="w-full truncate">{entry.name}</span>
                <span className={cn(textVariants({ variant: "hint" }), "w-full truncate")}>
                  {savedConditionSummary(entry)}
                </span>
              </Button>
              <Button
                variant="ghost"
                size="bare"
                className="flex-none p-1 text-xs"
                aria-label={`「${entry.name}」を消す`}
                onClick={() => onRemove(entry.name)}
              >
                ✕
              </Button>
            </li>
          ))}
        </ul>
      )}
      <p role="status" className={textVariants({ variant: "hint" })}>
        {recalledName !== null && saved.some((entry) => entry.name === recalledName)
          ? `「${recalledName}」の条件にしました。`
          : ""}
      </p>
    </div>
  );
}

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { buttonVariants } from "../Button/Button";
import {
  GenerateRoutesIcon,
  RouteDiffIcon,
  SaveConditionsIcon,
  SavePlaceIcon,
  type MapIconComponent,
} from "../icons/icons";

// 案内の文の中で、アイコンだけのパネルの操作を「名前」で指した所を、そのボタンと同じ見た目のアイコンにして描く
// （docs/modules/frontend/frontend-design-system.md 5-1）。名前はボタンの`aria-label`と同じにする——
// 読み上げと吹き出しには、ボタンと同じ名前を残す。
const BUTTON_MARKS = new Map<string, { Icon: MapIconComponent; variant: "primary" | "secondary" }>([
  ["ルート生成", { Icon: GenerateRoutesIcon, variant: "primary" }],
  ["差分を見る", { Icon: RouteDiffIcon, variant: "secondary" }],
  ["地点を保存", { Icon: SavePlaceIcon, variant: "secondary" }],
  ["いまの設定を保存", { Icon: SaveConditionsIcon, variant: "secondary" }],
]);

const QUOTED_NAME = /「([^「」]+)」/g;

/** 案内の文。ここに無い名前（「ルート設定」等）は、かぎ括弧ごと文字のまま残す。 */
export function GuideText({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let rest = 0;
  for (const match of text.matchAll(QUOTED_NAME)) {
    const name = match[1];
    const mark = BUTTON_MARKS.get(name);
    if (!mark) continue;
    parts.push(text.slice(rest, match.index));
    parts.push(
      <span
        key={match.index}
        title={name}
        className={cn(
          buttonVariants({ variant: mark.variant, size: "bare" }),
          "mx-0.5 cursor-default px-1 py-0.5 align-middle",
        )}
      >
        <mark.Icon size={14} />
        <span className="sr-only">{name}</span>
      </span>,
    );
    rest = match.index + match[0].length;
  }
  parts.push(text.slice(rest));
  return <>{parts}</>;
}

"use client";

import { forwardRef, useEffect, useRef, useState } from "react";
import { controlClass } from "@/components/ui/Input/Input";
import { cn } from "@/lib/cn";

// 数値の入力欄。入力途中の文字（空・「-」・「1.」等）は数として読めないため、値（number）だけを
// 持つと打った文字が消える。打っている間の文字はこの部品が持ち、欄を離れると値の表示へ戻す。
//
// いつ値を渡すかは`commitOn`で選ぶ:
// - "input": 数として読めた時点で毎回渡す（グラフを見ながら折れ点を動かす等、打った先から効かせたいとき）
// - "commit": 欄を離れたとき・Enterで1回だけ渡す（走行条件の速度のように、桁の途中の値を効かせたくないとき）
//
// "commit"で打ったまま欄ごと消えた（ポップオーバーをEscで閉じた等。消える要素にはblurが届かない）ときも、
// 打った値を渡す。
//
// 範囲への丸めは呼び出し側が値で行う（丸めた結果が前と同じ値でも、欄を離れれば表示は値へ戻る）。
interface NumberInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> {
  value: number;
  onValueChange: (next: number) => void;
  commitOn: "input" | "commit";
}

function parse(text: string): number | null {
  if (text.trim() === "") return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

export const NumberInput = forwardRef<HTMLInputElement, NumberInputProps>(function NumberInput(
  { value, onValueChange, commitOn, onFocus, onBlur, onKeyDown, className, ...rest },
  ref,
) {
  const [draft, setDraft] = useState<string | null>(null);
  const pendingRef = useRef<{ draft: string | null; onValueChange: (next: number) => void }>({ draft, onValueChange });
  useEffect(() => {
    pendingRef.current = { draft, onValueChange };
  });
  useEffect(
    () => () => {
      const { draft: left, onValueChange: send } = pendingRef.current;
      const parsed = left === null ? null : parse(left);
      if (commitOn === "commit" && parsed !== null) send(parsed);
    },
    [commitOn],
  );
  const commit = (text: string | null) => {
    setDraft(null);
    if (text === null || commitOn !== "commit") return;
    const parsed = parse(text);
    if (parsed !== null) onValueChange(parsed);
  };
  return (
    <input
      ref={ref}
      type="number"
      className={cn(controlClass, className)}
      value={draft ?? String(value)}
      onFocus={(event) => {
        event.currentTarget.select();
        onFocus?.(event);
      }}
      onChange={(event) => {
        const text = event.target.value;
        setDraft(text);
        if (commitOn === "input") {
          const parsed = parse(text);
          if (parsed !== null) onValueChange(parsed);
        }
      }}
      onBlur={(event) => {
        commit(draft);
        onBlur?.(event);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit(draft);
        onKeyDown?.(event);
      }}
      {...rest}
    />
  );
});

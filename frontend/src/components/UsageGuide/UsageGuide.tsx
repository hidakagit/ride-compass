"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Popover, PopoverAnchor, PopoverContent, POPOVER_COLLISION_PADDING_PX } from "@/components/ui/Popover/Popover";
import { Button } from "@/components/ui/Button/Button";
import { GuideText } from "@/components/ui/GuideText/GuideText";
import { textVariants } from "@/components/ui/Text/Text";
import { cardVariants } from "@/components/ui/Card/Card";
import { cn } from "@/lib/cn";
import { USAGE_GUIDE_ATTRIBUTE, usageTargetOf, type UsageTarget } from "./usageTarget";

/** 押してから離すまでにこれ以上動いたら、押したのではなく動かした（なぞった・スクロールした）とみなす。 */
const TAP_SLOP_PX = 10;

/** 値を動かすキー。説明を見る状態では、フォーカスのある部品の値を変えさせない。 */
const VALUE_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"]);

/** 部品を動かすマウス・タッチの出来事。止めるだけにし、タッチは既定の動き（スクロール）を残す。 */
const MOUSE_EVENTS = ["mousedown", "mouseup", "click", "dblclick", "auxclick", "contextmenu"] as const;
const TOUCH_EVENTS = ["touchstart", "touchmove", "touchend"] as const;

interface UsageGuideProps {
  /** 説明を見る状態を終える（「やめる」・説明の✕・Esc・説明を出している間に部品の外を押したとき）。 */
  onEnd: () => void;
}

function isInGuide(event: Event): boolean {
  return event.target instanceof Element && event.target.closest(`[${USAGE_GUIDE_ATTRIBUTE}]`) !== null;
}

/**
 * 説明を見る状態。出している間は、画面のどの部品を押しても部品は動かず、押した部品の使い方を出す。
 * 押す操作は窓の捕捉段階で1か所で止めるので、部品の側は止め方を持たない（持つのは使い方の文だけ）。
 * 置いた要素の上端の中央に案内を出す。
 */
export default function UsageGuide({ onEnd }: UsageGuideProps) {
  const [target, setTarget] = useState<UsageTarget | null>(null);
  const [highlight, setHighlight] = useState<DOMRect | null>(null);
  const onEndRef = useRef(onEnd);
  const targetRef = useRef<UsageTarget | null>(null);
  useEffect(() => {
    onEndRef.current = onEnd;
    targetRef.current = target;
  });

  useEffect(() => {
    let down: { x: number; y: number } | null = null;

    const choose = (pressed: EventTarget | null, end: () => void) => {
      const found = pressed instanceof Element ? usageTargetOf(pressed) : null;
      if (found) setTarget(found);
      // 説明を出している間に部品の外を押したら、説明を閉じる（ほかの浮きパネルと同じ）。
      else if (targetRef.current) end();
    };
    // 離したときに閉じると、その押し操作の残りのマウスの出来事（click 等）は閉じたあとに届くので、click まで止め続ける。
    // click の来ない押し方（タッチの長押し等）でも残らないよう、次の押し操作かキー操作で止めるのをやめる。
    const endByPress = () => {
      const swallow = (event: Event) => {
        event.stopPropagation();
        event.preventDefault();
        if (event.type === "click") release();
      };
      const release = () => {
        for (const type of MOUSE_EVENTS) window.removeEventListener(type, swallow, true);
        window.removeEventListener("pointerdown", release, true);
        window.removeEventListener("keydown", release, true);
      };
      for (const type of MOUSE_EVENTS) window.addEventListener(type, swallow, true);
      window.addEventListener("pointerdown", release, true);
      window.addEventListener("keydown", release, true);
      onEndRef.current();
    };
    const onPointerDown = (event: PointerEvent) => {
      if (isInGuide(event)) return;
      down = { x: event.clientX ?? 0, y: event.clientY ?? 0 };
      event.stopPropagation();
      event.preventDefault();
    };
    // 押せない（disabled）ボタンにはclickが届かないため、離したときに決める。
    const onPointerUp = (event: PointerEvent) => {
      if (isInGuide(event)) return;
      event.stopPropagation();
      const start = down;
      down = null;
      if (start === null) return;
      if (Math.hypot((event.clientX ?? 0) - start.x, (event.clientY ?? 0) - start.y) > TAP_SLOP_PX) return;
      choose(event.target, endByPress);
    };
    const onPointerCancel = () => {
      down = null;
    };
    const stopMouse = (event: Event) => {
      if (isInGuide(event)) return;
      event.stopPropagation();
      event.preventDefault();
    };
    const stopTouch = (event: Event) => {
      if (isInGuide(event)) return;
      event.stopPropagation();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        event.preventDefault();
        onEndRef.current();
        return;
      }
      if (isInGuide(event)) return;
      if (event.key === "Enter" || event.key === " ") {
        event.stopPropagation();
        event.preventDefault();
        choose(document.activeElement, () => onEndRef.current());
      } else if (VALUE_KEYS.has(event.key)) {
        event.stopPropagation();
        event.preventDefault();
      }
    };

    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("pointerup", onPointerUp, true);
    window.addEventListener("pointercancel", onPointerCancel, true);
    window.addEventListener("keydown", onKeyDown, true);
    for (const type of MOUSE_EVENTS) window.addEventListener(type, stopMouse, true);
    for (const type of TOUCH_EVENTS) window.addEventListener(type, stopTouch, true);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("pointerup", onPointerUp, true);
      window.removeEventListener("pointercancel", onPointerCancel, true);
      window.removeEventListener("keydown", onKeyDown, true);
      for (const type of MOUSE_EVENTS) window.removeEventListener(type, stopMouse, true);
      for (const type of TOUCH_EVENTS) window.removeEventListener(type, stopTouch, true);
    };
  }, []);

  // 説明している部品を枠で示す。下部シートの中をスクロールしても部品に付いていくよう、測り直す。
  useEffect(() => {
    if (target === null) return;
    const measure = () => setHighlight(target.element.getBoundingClientRect());
    measure();
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [target]);

  const anchor = useMemo(() => ({ current: target?.element ?? null }), [target]);

  return (
    <>
      <div
        {...{ [USAGE_GUIDE_ATTRIBUTE]: "" }}
        role="status"
        // 案内の下の部品も押せるよう、案内は押す操作を素通しし、「やめる」だけが受ける。
        className={cn(
          cardVariants({ variant: "float" }),
          "pointer-events-none absolute top-16 left-1/2 z-[var(--z-usage-guide)] flex w-max max-w-[calc(100%-2*var(--space-3))] -translate-x-1/2 items-center gap-2 px-3 py-1.5 text-[length:var(--font-size-sm)]",
        )}
      >
        <span>説明を見たい部品を押してください</span>
        <Button size="xs" className="pointer-events-auto" onClick={() => onEndRef.current()}>
          やめる
        </Button>
      </div>
      {highlight && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed z-[var(--z-usage-guide)] rounded-sm outline-2 outline-offset-2 outline-[var(--color-accent-strong)]"
          style={{ left: highlight.left, top: highlight.top, width: highlight.width, height: highlight.height }}
        />
      )}
      <Popover
        open={target !== null}
        onOpenChange={(open) => {
          if (!open) onEndRef.current();
        }}
      >
        <PopoverAnchor virtualRef={anchor} />
        <PopoverContent
          {...{ [USAGE_GUIDE_ATTRIBUTE]: "" }}
          layer="guide"
          className="flex max-w-72 flex-col gap-1"
          collisionPadding={POPOVER_COLLISION_PADDING_PX}
          aria-label="使い方の説明"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="m-0 font-semibold">{target?.name ?? "この部品"}</p>
            <Button
              variant="ghost"
              size="bare"
              className="px-1"
              aria-label="説明を閉じる"
              onClick={() => onEndRef.current()}
            >
              ✕
            </Button>
          </div>
          <p className={cn(textVariants({ variant: target?.usage ? "body" : "hint" }), "m-0")}>
            {target?.usage ? <GuideText text={target.usage} /> : "この部品の説明はまだありません。"}
          </p>
        </PopoverContent>
      </Popover>
    </>
  );
}

"use client";

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Popover, PopoverAnchor, PopoverContent, POPOVER_COLLISION_PADDING_PX } from "@/components/ui/Popover/Popover";
import { Button } from "@/components/ui/Button/Button";
import { GuideText } from "@/components/ui/GuideText/GuideText";
import { textVariants } from "@/components/ui/Text/Text";
import FloatingPanel from "@/components/FloatingPanel/FloatingPanel";
import { cn } from "@/lib/cn";
import {
  USAGE_GUIDE_ATTRIBUTE,
  isInUsageGuide,
  isUnselectedTab,
  usageTargetOf,
  type UsageTarget,
} from "./usageTarget";

/** 押してから離すまでにこれ以上動いたら、押したのではなく動かした（なぞった・スクロールした）とみなす。 */
const TAP_SLOP_PX = 10;

/** 値を動かすキー。説明を見る状態では、フォーカスのある部品の値を変えさせない。 */
const VALUE_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"]);

/** 部品を動かすマウス・タッチの出来事。止めるだけにし、タッチは既定の動き（スクロール）を残す。 */
const MOUSE_EVENTS = ["mousedown", "mouseup", "click", "dblclick", "auxclick", "contextmenu"] as const;
const TOUCH_EVENTS = ["touchstart", "touchmove", "touchend"] as const;

interface UsageGuideProps {
  /** 説明を見る状態を終える（「やめる」・Escのときだけ）。 */
  onEnd: () => void;
}

/** 止めている押し操作の外で、部品を押す（開くボタンで浮きパネルを開く、タブを切り替える）。押す間は`passing`を立てる。 */
function pressThrough(element: Element, passing: RefObject<boolean>) {
  if (!(element instanceof HTMLElement)) return;
  passing.current = true;
  try {
    if (isUnselectedTab(element)) element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    else element.click();
  } finally {
    passing.current = false;
  }
}

/**
 * 説明を見る状態。出している間は、画面のどの部品を押しても部品は動かず、押した部品の使い方を出す。
 * 押す操作は窓の捕捉段階で1か所で止めるので、部品の側は止め方を持たない（持つのは使い方の文だけ）。
 * 終えるのは案内の「やめる」とEscだけで、ほかの抜け方（部品の外を押す・説明の外へのフォーカス）は説明だけを閉じる。
 * 案内は画面の上の中央に浮かべ、つまみで動かせる。説明の面は部品の下に出し、置き方はRadixの位置取りに任せる。
 */
export default function UsageGuide({ onEnd }: UsageGuideProps) {
  const [target, setTarget] = useState<UsageTarget | null>(null);
  const [highlight, setHighlight] = useState<DOMRect | null>(null);
  const onEndRef = useRef(onEnd);
  /** 自分で押す click を止めずに届ける間か。 */
  const passing = useRef(false);
  useEffect(() => {
    onEndRef.current = onEnd;
  });

  useEffect(() => {
    let down: { x: number; y: number } | null = null;

    const choose = (pressed: EventTarget | null) => {
      const element = pressed instanceof Element ? pressed : undefined;
      // 部品ならその説明に替え、部品の外なら説明だけを閉じる（✕と同じ）。
      setTarget(element ? usageTargetOf(element) : null);
    };
    const onPointerDown = (event: PointerEvent) => {
      if (isInUsageGuide(event.target)) return;
      down = { x: event.clientX ?? 0, y: event.clientY ?? 0 };
      event.stopPropagation();
      event.preventDefault();
    };
    // 押せない（disabled）ボタンにはclickが届かないため、離したときに決める。
    const onPointerUp = (event: PointerEvent) => {
      if (isInUsageGuide(event.target)) return;
      event.stopPropagation();
      const start = down;
      down = null;
      if (start === null) return;
      if (Math.hypot((event.clientX ?? 0) - start.x, (event.clientY ?? 0) - start.y) > TAP_SLOP_PX) return;
      choose(event.target);
    };
    const onPointerCancel = () => {
      down = null;
    };
    const stopMouse = (event: Event) => {
      if (passing.current || isInUsageGuide(event.target)) return;
      event.stopPropagation();
      event.preventDefault();
    };
    const stopTouch = (event: Event) => {
      if (isInUsageGuide(event.target)) return;
      event.stopPropagation();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        event.preventDefault();
        onEndRef.current();
        return;
      }
      if (isInUsageGuide(event.target)) return;
      if (event.key === "Enter" || event.key === " ") {
        event.stopPropagation();
        event.preventDefault();
        choose(document.activeElement);
      } else if (VALUE_KEYS.has(event.key)) {
        event.stopPropagation();
        event.preventDefault();
      }
    };

    const listening = new AbortController();
    const options = { capture: true, signal: listening.signal };
    window.addEventListener("pointerdown", onPointerDown, options);
    window.addEventListener("pointerup", onPointerUp, options);
    window.addEventListener("pointercancel", onPointerCancel, options);
    window.addEventListener("keydown", onKeyDown, options);
    for (const type of MOUSE_EVENTS) window.addEventListener(type, stopMouse, options);
    for (const type of TOUCH_EVENTS) window.addEventListener(type, stopTouch, options);
    return () => listening.abort();
  }, []);

  // 説明している部品を枠で示す。下部シートの中をスクロールしても部品に付いていくよう、測り直す。
  useEffect(() => {
    if (target === null) return;
    const measure = () => {
      const next = target.element.getBoundingClientRect();
      setHighlight((current) =>
        current !== null &&
        current.left === next.left &&
        current.top === next.top &&
        current.width === next.width &&
        current.height === next.height
          ? current
          : next,
      );
    };
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
      <div {...{ [USAGE_GUIDE_ATTRIBUTE]: "" }} role="status">
        {/* 案内は見出しと「やめる」の1行だけ。部品の上に重なってよい（つまみで動かせる）。浮きパネルを開いている間も、その上に出す。 */}
        <FloatingPanel
          open
          onClose={() => onEndRef.current()}
          title="説明モード"
          closeLabel="やめる"
          layer="guide"
          topRem={4.25}
          widthRem={11}
        />
      </div>
      {target && highlight && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed z-[var(--z-usage-guide)] rounded-sm outline-2 outline-offset-2 outline-[var(--color-accent-strong)]"
          style={{ left: highlight.left, top: highlight.top, width: highlight.width, height: highlight.height }}
        />
      )}
      <Popover
        open={target !== null}
        // 説明の外へのフォーカスでも、説明だけを閉じる。
        onOpenChange={(open) => {
          if (!open) setTarget(null);
        }}
      >
        <PopoverAnchor virtualRef={anchor} />
        <PopoverContent
          {...{ [USAGE_GUIDE_ATTRIBUTE]: "" }}
          side="bottom"
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
              // 説明だけを閉じ、部品を選ぶ続きへ戻る。
              onClick={() => setTarget(null)}
            >
              ✕
            </Button>
          </div>
          <p className={cn(textVariants({ variant: target?.usage ? "body" : "hint" }), "m-0")}>
            {target?.usage ? <GuideText text={target.usage} /> : "この部品の説明はまだありません。"}
          </p>
          {target?.opens && (
            <Button
              size="xs"
              className="self-start"
              // 中を展開して説明だけを閉じ、中の部品を選ぶ続きへ戻る。開いた先は、終えたあとも開いたまま残る。
              onClick={() => {
                pressThrough(target.element, passing);
                setTarget(null);
              }}
            >
              中を見る
            </Button>
          )}
        </PopoverContent>
      </Popover>
    </>
  );
}

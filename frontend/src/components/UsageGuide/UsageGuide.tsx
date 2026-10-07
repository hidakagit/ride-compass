"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Popover, PopoverAnchor, PopoverContent, POPOVER_COLLISION_PADDING_PX } from "@/components/ui/Popover/Popover";
import { Button } from "@/components/ui/Button/Button";
import { GuideText } from "@/components/ui/GuideText/GuideText";
import { textVariants } from "@/components/ui/Text/Text";
import FloatingPanel from "@/components/FloatingPanel/FloatingPanel";
import { cn } from "@/lib/cn";
import {
  USAGE_GUIDE_ATTRIBUTE,
  USAGE_PART_SELECTOR,
  isPopoverOpener,
  usageTargetOf,
  type UsageTarget,
} from "./usageTarget";
import { chooseUsagePlacement, type UsagePlacement } from "./usagePlacement";

/** 押してから離すまでにこれ以上動いたら、押したのではなく動かした（なぞった・スクロールした）とみなす。 */
const TAP_SLOP_PX = 10;

/** 値を動かすキー。説明を見る状態では、フォーカスのある部品の値を変えさせない。 */
const VALUE_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"]);

/** 部品を動かすマウス・タッチの出来事。止めるだけにし、タッチは既定の動き（スクロール）を残す。 */
const MOUSE_EVENTS = ["mousedown", "mouseup", "click", "dblclick", "auxclick", "contextmenu"] as const;
const TOUCH_EVENTS = ["touchstart", "touchmove", "touchend"] as const;

/** 説明の面と部品の間。 */
const PANEL_OFFSET_PX = 6;

interface UsageGuideProps {
  /** 説明を見る状態を終える（「やめる」・Escのときだけ）。 */
  onEnd: () => void;
}

/** 「中を見る」で開いた浮きパネルの開くボタン（開いた順。閉じたあとフォーカスが戻るのを見分けるため、閉じたものも残す）と、自分で押す click を止めずに届ける間か。 */
interface Opening {
  openers: Element[];
  passing: boolean;
}

function isInGuide(event: Event): boolean {
  return event.target instanceof Element && event.target.closest(`[${USAGE_GUIDE_ATTRIBUTE}]`) !== null;
}

/** 開くボタンが開いている浮きパネル（Radix は開いている間だけ`aria-controls`で中身を指す）。閉じていれば null。 */
function openedPanelOf(opener: Element): Element | null {
  const id = opener.getAttribute("aria-controls");
  return id ? opener.ownerDocument.getElementById(id) : null;
}

function isAnyOpen(opening: RefObject<Opening>): boolean {
  return opening.current.openers.some((opener) => openedPanelOf(opener) !== null);
}

/** 止めている押し操作の外で、部品を押す（開くボタンで浮きパネルを開く・閉じる）。 */
function pressThrough(element: Element, opening: RefObject<Opening>) {
  if (!(element instanceof HTMLElement)) return;
  opening.current.passing = true;
  try {
    element.click();
  } finally {
    opening.current.passing = false;
  }
}

/** 「中を見る」で開いた浮きパネルを、後に開いたものから閉じる。`keep`を中に持つものとその外側は残す。 */
function closeOpened(opening: RefObject<Opening>, keep?: Element) {
  for (const opener of [...opening.current.openers].reverse()) {
    const panel = openedPanelOf(opener);
    if (panel === null) continue;
    if (keep !== undefined && panel.contains(keep)) return;
    pressThrough(opener, opening);
  }
}

/** 説明を見る状態を終える。「中を見る」で開いた浮きパネルも一緒に閉じる。 */
function endGuide(opening: RefObject<Opening>, onEnd: RefObject<() => void>) {
  closeOpened(opening);
  onEnd.current();
}

/** 説明している部品のほかに、いま押せる部品の箱（押す点＝中心点が、説明の面を除いて最前面にあるもの）。 */
function pressablePartsBesides(target: Element, panel: Element): DOMRect[] {
  const parts: DOMRect[] = [];
  for (const part of document.querySelectorAll(USAGE_PART_SELECTOR)) {
    if (panel.contains(part) || part.contains(target) || target.contains(part)) continue;
    const rect = part.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    // 面と、面を包む位置取りの要素は、まだ前の位置にあるので除いて見る。
    const hit = document
      .elementsFromPoint(x, y)
      .find((element) => !panel.contains(element) && !element.contains(panel));
    if (hit !== undefined && part.contains(hit)) parts.push(rect);
  }
  return parts;
}

/**
 * 説明を見る状態。出している間は、画面のどの部品を押しても部品は動かず、押した部品の使い方を出す。
 * 押す操作は窓の捕捉段階で1か所で止めるので、部品の側は止め方を持たない（持つのは使い方の文だけ）。
 * 終えるのは案内の「やめる」とEscだけで、ほかの抜け方（部品の外を押す・説明の外へのフォーカス）は説明だけを閉じる。
 * 案内は画面の上の中央に浮かべ、つまみで動かせる。説明の面は、ほかの部品と案内にできるだけ重ねない所へ出す。
 */
export default function UsageGuide({ onEnd }: UsageGuideProps) {
  const [target, setTarget] = useState<UsageTarget | null>(null);
  const [highlight, setHighlight] = useState<DOMRect | null>(null);
  const [panel, setPanel] = useState<HTMLDivElement | null>(null);
  const bannerRef = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<UsagePlacement>({
    side: "bottom",
    sideOffset: PANEL_OFFSET_PX,
    alignOffset: 0,
  });
  const onEndRef = useRef(onEnd);
  const opening = useRef<Opening>({ openers: [], passing: false });
  useEffect(() => {
    onEndRef.current = onEnd;
  });

  useEffect(() => {
    let down: { x: number; y: number } | null = null;

    const choose = (pressed: EventTarget | null) => {
      const element = pressed instanceof Element ? pressed : undefined;
      const found = element ? usageTargetOf(element) : null;
      // 開いた浮きパネルの外を押したら、浮きパネルを閉じる。
      closeOpened(opening, found?.element ?? element);
      // 部品ならその説明に替え、部品の外なら説明だけを閉じる（✕と同じ）。
      setTarget(found);
    };
    const onPointerDown = (event: PointerEvent) => {
      if (isInGuide(event)) {
        // 開いた浮きパネルは、案内と面の上の押し操作を外を押したと読んで閉じるので、届けない。
        if (isAnyOpen(opening)) event.stopPropagation();
        return;
      }
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
      choose(event.target);
    };
    const onPointerCancel = () => {
      down = null;
    };
    const stopMouse = (event: Event) => {
      if (opening.current.passing) return;
      if (isInGuide(event)) {
        // 押してもフォーカスを面へ移さない。移ると、開いた浮きパネルは外へのフォーカスで閉じる。
        if (event.type === "mousedown" && isAnyOpen(opening)) event.preventDefault();
        return;
      }
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
        endGuide(opening, onEndRef);
        return;
      }
      if (isInGuide(event)) return;
      if (event.key === "Enter" || event.key === " ") {
        event.stopPropagation();
        event.preventDefault();
        choose(document.activeElement);
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

  // 面の大きさは中身（部品の名前と文）で決まるので、中身が替わるたびに描いてから測り、描き直す前に向きを決める。
  useLayoutEffect(() => {
    if (target === null || panel === null) return;
    setPlacement(
      chooseUsagePlacement(
        target.element.getBoundingClientRect(),
        { width: panel.offsetWidth, height: panel.offsetHeight },
        { width: window.innerWidth, height: window.innerHeight },
        [
          ...pressablePartsBesides(target.element, panel),
          // 案内の箱は、包む要素の中の位置取りの要素（`FloatingPanel`が画面に固定して置く）が持つ。
          ...(bannerRef.current?.firstElementChild
            ? [bannerRef.current.firstElementChild.getBoundingClientRect()]
            : []),
        ],
        PANEL_OFFSET_PX,
        POPOVER_COLLISION_PADDING_PX,
      ),
    );
  }, [target, panel]);

  const anchor = useMemo(() => ({ current: target?.element ?? null }), [target]);

  return (
    <>
      <div {...{ [USAGE_GUIDE_ATTRIBUTE]: "" }} ref={bannerRef} role="status">
        {/* 案内は見出しと「やめる」の1行だけ。部品の上に重なってよい（つまみで動かせる）。浮きパネルを開いている間も、その上に出す。 */}
        <FloatingPanel
          open
          onClose={() => endGuide(opening, onEndRef)}
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
          ref={setPanel}
          side={placement.side}
          align="start"
          sideOffset={placement.sideOffset}
          alignOffset={placement.alignOffset}
          // 既定（partial）は面を部品から離れないところまで寄せ戻し、離して選んだ位置がずれる。
          sticky="always"
          layer="guide"
          className="flex max-w-72 flex-col gap-1"
          collisionPadding={POPOVER_COLLISION_PADDING_PX}
          aria-label="使い方の説明"
          // 案内を動かしても、説明は閉じない。
          onPointerDownOutside={(event) => {
            if (isInGuide(event)) event.preventDefault();
          }}
          // 浮きパネルを開いている間は、面へフォーカスを移さず、浮きパネルの中と開くボタンへのフォーカスで閉じない
          // （浮きパネルは外へのフォーカスで閉じ、閉じると開くボタンへフォーカスを戻す）。
          onOpenAutoFocus={(event) => {
            if (isAnyOpen(opening)) event.preventDefault();
          }}
          onFocusOutside={(event) => {
            const focused = event.target;
            const opened = opening.current.openers.some(
              (opener) => opener === focused || (focused instanceof Node && openedPanelOf(opener)?.contains(focused)),
            );
            if (opened) event.preventDefault();
          }}
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
              // 中を展開して説明だけを閉じ、中の部品を選ぶ続きへ戻る。浮きパネルは、外の部品を押したときと終えるときに閉じる。
              onClick={() => {
                const opener = target.element;
                if (isPopoverOpener(opener))
                  opening.current.openers = [...opening.current.openers.filter((o) => o !== opener), opener];
                pressThrough(opener, opening);
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

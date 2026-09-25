"use client";

import { useEffect, useRef } from "react";
import useEmblaCarousel from "embla-carousel-react";
import { WheelGesturesPlugin } from "embla-carousel-wheel-gestures";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { cardVariants } from "@/components/ui/Card/Card";

/** スライダーの1コマ。`label`は日付付きの日時（目盛りの文字は日付を持たないので、日付をまたぐ曖昧さはこれが解く）。
 * `hourMark`は目盛りを太く、コマを広くする。`tickLabel`は目盛りの下の短い文字（重ならないよう呼ぶ側が間引く）。 */
export interface DynamicLayerTimeSliderFrame {
  label: string;
  hourMark?: boolean;
  tickLabel?: string;
}

// 目盛りの間隔（px）。正時のコマは広げる。
const TICK_SPACING_PX = 18;
const TICK_SPACING_HOUR_PX = 28;
// 選んだコマを合わせる左端の目印の位置（px）。コマの幅によらない。
const INDICATOR_OFFSET_PX = TICK_SPACING_PX / 2;

function frameWidth(frame: DynamicLayerTimeSliderFrame): number {
  return frame.hourMark ? TICK_SPACING_HOUR_PX : TICK_SPACING_PX;
}

interface DynamicLayerTimeSliderProps {
  frames: readonly DynamicLayerTimeSliderFrame[];
  /** framesの添字（framesは1コマ以上）。 */
  index: number;
  onIndexChange: (index: number) => void;
  /** 「今」にあたる添字。「現在」ボタンを押せなくする判定にだけ使う。 */
  currentIndex: number;
  /** 「現在」ボタン。`currentIndex`へは飛ばない（目盛りへ丸めた近似で、実時刻より粗い）。 */
  onNow: () => void;
  ariaLabel: string;
}

// 可変幅のコマ・ホイールの横スクロール・離した位置への吸着はEmblaが持ち、コマの中心を左端の目印へ合わせる。
// キーボード操作とsliderのARIAはEmblaに無いので自前で持つ。
const emblaOptions = {
  axis: "x" as const,
  align: (viewSize: number, snapSize: number) => INDICATOR_OFFSET_PX - snapSize / 2,
  containScroll: false as const,
  dragFree: false,
};

/** ドラッグ・横スクロールで時刻のコマを選ぶルーラー。時刻の計算は知らない（コマの並びは呼ぶ側が作る）。 */
export default function DynamicLayerTimeSlider({
  frames,
  index,
  onIndexChange,
  currentIndex,
  onNow,
  ariaLabel,
}: DynamicLayerTimeSliderProps) {
  const [emblaRef, emblaApi] = useEmblaCarousel(emblaOptions, [WheelGesturesPlugin({ forceWheelAxis: "x" })]);
  // 最後に自分が報告した（または反映済みの）添字。外から変わったときだけスクロールし直す（自分のドラッグの報告で
  // 変わるたびにスクロールすると、ループになる）。
  const syncedIndexRef = useRef(index);
  // 初回はアニメーションさせずに合わせる。
  const hasMountedRef = useRef(false);

  useEffect(() => {
    if (!emblaApi) return;
    const alreadySynced = index === syncedIndexRef.current;
    if (hasMountedRef.current && alreadySynced) return;
    syncedIndexRef.current = index;
    const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    emblaApi.scrollTo(index, !hasMountedRef.current || prefersReducedMotion);
    hasMountedRef.current = true;
  }, [emblaApi, index]);

  // 選んだコマが変わるたびに報告する。`settle`は速いドラッグの後に来ないことがあるので、コマをまたいだときだけ
  // 来る`select`を使う。
  useEffect(() => {
    if (!emblaApi) return;
    const handleSelect = () => {
      const next = emblaApi.selectedScrollSnap();
      if (next !== syncedIndexRef.current) {
        syncedIndexRef.current = next;
        onIndexChange(next);
      }
    };
    emblaApi.on("select", handleSelect);
    return () => {
      emblaApi.off("select", handleSelect);
    };
  }, [emblaApi, onIndexChange]);

  // スクロールの追従は外からの変化としてuseEffectが受ける。
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    let next: number | null = null;
    if (e.key === "ArrowRight") next = Math.min(frames.length - 1, index + 1);
    else if (e.key === "ArrowLeft") next = Math.max(0, index - 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = frames.length - 1;
    if (next !== null && next !== index) {
      e.preventDefault();
      onIndexChange(next);
    }
  };

  // 端では押せないので、動かした先は必ず範囲の中。
  const stepIndex = (delta: number) => onIndexChange(index + delta);

  const frame = frames[index];

  return (
    <div className="pointer-events-none">
      <div
        className={cn(
          cardVariants({ variant: "float" }),
          "flex w-[min(90vw,26rem)] max-w-[min(26rem,100%)] flex-col gap-1 rounded-sm px-2 py-1.5",
        )}
      >
        <div className={cn(textVariants({ variant: "heading" }), "pointer-events-auto touch-none tabular-nums")}>
          {frame.label}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="stepper"
            size="sm"
            className="pointer-events-auto touch-none"
            onClick={() => stepIndex(-1)}
            disabled={index <= 0}
            aria-label={`${ariaLabel}を1つ前へ`}
            title="1つ前へ"
          >
            ‹
          </Button>
          <div
            ref={emblaRef}
            className="pointer-events-auto relative h-8 min-w-30 flex-1 cursor-grab touch-none overflow-x-auto overflow-y-hidden select-none [-webkit-tap-highlight-color:transparent] [-webkit-user-drag:none] [scrollbar-width:none] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)] [&::-webkit-scrollbar]:hidden"
            onKeyDown={handleKeyDown}
            role="slider"
            tabIndex={0}
            aria-label={ariaLabel}
            aria-orientation="horizontal"
            aria-valuemin={0}
            aria-valuemax={frames.length - 1}
            aria-valuenow={index}
            aria-valuetext={frame.label}
          >
            <div className="flex h-full">
              {frames.map((f, i) => (
                <div
                  key={i}
                  className="group flex flex-shrink-0 flex-col items-center justify-start pt-2"
                  data-hour={f.hourMark}
                  style={{ width: frameWidth(f) }}
                >
                  <span
                    className="h-2 w-px bg-[var(--color-border-strong)] group-data-[hour=true]:h-3.5 group-data-[hour=true]:w-0.5 group-data-[hour=true]:bg-[var(--color-muted-strong)]"
                    aria-hidden="true"
                  />
                  {/* 文字の無いコマも高さを確保する（縦の位置が揃うように）。 */}
                  <span className="mt-1 block h-3 max-w-9 truncate text-[0.55rem] leading-3 text-[var(--color-muted)] tabular-nums">
                    {f.tickLabel ?? ""}
                  </span>
                </div>
              ))}
            </div>
            <div
              className="pointer-events-none absolute top-0.5 h-6 w-0.5 -translate-x-1/2 rounded-full bg-[var(--color-accent)]"
              style={{ left: INDICATOR_OFFSET_PX }}
              aria-hidden="true"
            />
          </div>
          <Button
            variant="stepper"
            size="sm"
            className="pointer-events-auto touch-none"
            onClick={() => stepIndex(1)}
            disabled={index >= frames.length - 1}
            aria-label={`${ariaLabel}を1つ次へ`}
            title="1つ次へ"
          >
            ›
          </Button>
          <Button
            variant="stepper"
            size="sm"
            className="pointer-events-auto touch-none"
            onClick={onNow}
            disabled={index === currentIndex}
            aria-label={`${ariaLabel}を現在に戻す`}
            title="現在に戻す"
          >
            現在
          </Button>
        </div>
      </div>
    </div>
  );
}

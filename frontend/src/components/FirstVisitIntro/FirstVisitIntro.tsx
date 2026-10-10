"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button/Button";
import { GuideText } from "@/components/ui/GuideText/GuideText";
import { cardVariants } from "@/components/ui/Card/Card";
import { textVariants } from "@/components/ui/Text/Text";
import { MenuIcon } from "@/components/ui/icons/icons";
import { ORIGIN_MARK_FALLBACK_COLOR, PIN_MARK_BACKGROUND, PinMark } from "@/components/PinMark/PinMark";
import { useStoredBooleanState } from "@/hooks/useStoredState";
import { useIsomorphicLayoutEffect } from "@/hooks/useIsomorphicLayoutEffect";
import { cn } from "@/lib/cn";

const FIRST_VISIT_INTRO_STORAGE_KEY = "ridecompass:first-visit-intro-closed";

const TITLE_ID = "first-visit-intro-title";

interface FirstVisitIntroProps {
  /** 最初の一手の場所を、スマホ（下部タブ）とPC（左のパネル）で言い分ける。 */
  isMobile: boolean;
  /** 最初の位置の取得が決着して、位置が分からないと分かったか。真の間は出発地の印が灰色の仮の地点なので、
   * 「出発地を地図で選ぶ」で置く手順を案内する（決着するまでは「はじめは現在地」のまま）。 */
  locationUnknown: boolean;
}

/**
 * 初めて開いたときだけ地図の上に出す案内。閉じるとこの端末では次から出ない。
 * 保存値の復元はマウント後なので、マウントするまで出さない（出すとSSRのHTMLに載り、閉じた人にも一瞬見える）。
 */
export default function FirstVisitIntro({ isMobile, locationUnknown }: FirstVisitIntroProps) {
  const [closed, setClosed] = useStoredBooleanState(FIRST_VISIT_INTRO_STORAGE_KEY, false);
  const [mounted, setMounted] = useState(false);
  useIsomorphicLayoutEffect(() => setMounted(true), []);

  if (!mounted || closed) return null;

  return (
    <section
      aria-labelledby={TITLE_ID}
      className={cn(
        cardVariants({ variant: "float" }),
        "absolute top-16 left-1/2 z-[var(--z-map-detail)] flex w-[min(24rem,calc(100%-2*var(--space-3)))] -translate-x-1/2 flex-col gap-2 p-3",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h2 id={TITLE_ID} className={cn(textVariants({ variant: "heading" }), "m-0")}>
          RideCompass
        </h2>
        <Button variant="ghost" size="bare" className="px-1" aria-label="案内を閉じる" onClick={() => setClosed(true)}>
          ✕
        </Button>
      </div>
      <p className={cn(textVariants({ variant: "body" }), "m-0")}>
        ロードバイクで走る周回ルートを、道の走りやすさを評価して作ります。
      </p>
      <ul className={cn(textVariants({ variant: "body" }), "m-0 flex list-none flex-col gap-1.5 p-0")}>
        <li className="flex items-start gap-1.5">
          <span
            className="inline-flex shrink-0 rounded-full p-0.5 shadow-sm"
            style={{ background: PIN_MARK_BACKGROUND.origin }}
          >
            <PinMark role="origin" size={14} color={locationUnknown ? ORIGIN_MARK_FALLBACK_COLOR : undefined} />
          </span>
          <span>
            <GuideText
              text={
                locationUnknown
                  ? "現在地が分からないため、この灰色の印は仮の地点です。「ルート設定」の「出発地を地図で選ぶ」を押して地図をタップすると、そこが出発地になります。"
                  : "この印が出発地です（はじめは現在地）。地図の上でつかんで動かせます。"
              }
            />
          </span>
        </li>
        <li>
          <GuideText
            text={
              isMobile
                ? "下の「ルート設定」を開いて距離を決め、「ルート生成」を押すと、ルートの候補が地図に出ます。"
                : "左の「ルート設定」で距離を決め、「ルート生成」を押すと、ルートの候補が地図に出ます。"
            }
          />
        </li>
        <li>
          部品の使い方は、右上のメニュー（
          <span role="img" aria-label="メニュー" className="inline-flex align-[-2px]">
            <MenuIcon size={13} />
          </span>
          ）の「使い方を見る」から、部品を押して見られます。
        </li>
      </ul>
      <Button variant="primary" size="sm" className="self-end" onClick={() => setClosed(true)}>
        はじめる
      </Button>
    </section>
  );
}

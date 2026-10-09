"use client";

import { useEffect, useId, useRef } from "react";

import {
  ORIGIN_MARK_COLOR,
  ORIGIN_MARK_FALLBACK_COLOR,
  PIN_MARK_BACKGROUND,
  PinMark,
} from "@/components/PinMark/PinMark";
import { Button } from "@/components/ui/Button/Button";
import { Toggle } from "@/components/ui/Toggle/Toggle";
import { textVariants } from "@/components/ui/Text/Text";
import PlaceCandidates from "@/features/route/PlaceSearch/PlaceCandidates";
import { PREDICTION_MIN_LENGTH, usePlaceLookup } from "@/features/route/PlaceSearch/usePlaceLookup";
import { cn } from "@/lib/cn";
import type { Coordinates, PinRole, PlaceCandidate } from "@/types/route";

interface PointRowProps {
  role: PinRole;
  label: string;
  /** 行頭の印に入れる字（経由地の件数）。 */
  markLabel?: string;
  /** いまの値（現在地／探した名前／地図で指定／N地点／未設定）。何も打っていない間、欄の中に出す。 */
  value: string;
  /** 値が決まっているか（未設定・なしでない）。決まっている値は、打つ前の欄の中でも読める濃さで出す。 */
  valueSet: boolean;
  /** 地図で置く操作の名前（地図で選ぶ／追加／置き直す）。 */
  armLabel: string;
  /** 行の右端に並べる別の操作（✕・現在地に戻す）。 */
  extra?: React.ReactNode;
  /** 地図で置く状態の間に、値の代わりに出す文言。置いた数を隠さないため、経由地は件数を添える。 */
  armedHint?: string;
  /** 地図で置く操作の使い方の文。 */
  usage: string;
  /** 上限まで置いてあり、これ以上置けない（地図でも探してもの両方）。 */
  full?: boolean;
  armed: boolean;
  onArm: (role: PinRole | null) => void;
  /** 出発地の印を、実際の位置（現在地か置いた地点）の色で出すか。 */
  originLocated: boolean;
  /** 地図でいま見ている所の真ん中。施設の候補はここから近い順に並ぶ。 */
  mapCenter: Coordinates;
  /** 探して選んだ候補を、この行の役割の地点として置く。 */
  onPlaceFound: (role: PinRole, candidate: PlaceCandidate) => void;
}

/**
 * 出発地・経由地・目的地の1行。値の所は住所・施設の名前を打てる欄で、候補は行のすぐ下に出し、選ぶとこの行の役割で置く。
 * 地図で置く操作と、✕・現在地に戻すは欄の右に並べる。
 */
export default function PointRow({
  role,
  label,
  markLabel,
  value,
  valueSet,
  armLabel,
  extra,
  armedHint = "地図をタップ",
  usage,
  full = false,
  armed,
  onArm,
  originLocated,
  mapCenter,
  onPlaceFound,
}: PointRowProps) {
  const lookup = usePlaceLookup(mapCenter);
  const inputId = useId();
  const rowRef = useRef<HTMLDivElement>(null);
  const listing = lookup.query !== "";
  // 候補が出たら、行を面の上端へ送り、下の候補を面の高さいっぱいに見せる（狭い画面のシートでは、行の下に出した候補が面の下端で切れる）。
  // 一覧は自分では高さを限らず、面のスクロールだけで読む（二重のスクロールにしない）。
  // 候補が届いて一覧が伸びたときにも送り直す（引いている間の短い一覧では、面の下端まで送り切れない）。
  const candidates = lookup.search.data;
  useEffect(() => {
    if (listing) rowRef.current?.scrollIntoView({ block: "start" });
  }, [listing, candidates]);

  function choose(candidate: PlaceCandidate) {
    onPlaceFound(role, candidate);
    lookup.close({ clearText: true });
  }

  return (
    <div
      ref={rowRef}
      className="group scroll-mt-1 rounded-sm border border-[var(--color-border)] data-[armed=true]:border-[var(--color-accent)] data-[armed=true]:shadow-[inset_0_0_0_1px_var(--color-accent)]"
      data-armed={armed}
    >
      <form
        role="search"
        aria-label={label}
        className="flex items-center gap-1 pr-1"
        onSubmit={(event) => {
          event.preventDefault();
          lookup.submit();
        }}
      >
        {/* 印と名前を押しても欄に入れる（狭い画面で押す所を広く取る）。 */}
        <label htmlFor={inputId} className="flex flex-none items-center gap-2 py-1 pl-1.5">
          {/* 地図のピンと同じ図形を出す。同じものを2度描くと、片方だけ直したときに行とピンが違う見た目になる。 */}
          <span
            aria-hidden="true"
            className="inline-flex size-4.5 flex-none items-center justify-center rounded-full text-[0.7rem] text-white"
            style={{ background: PIN_MARK_BACKGROUND[role] }}
          >
            <PinMark
              role={role}
              label={markLabel}
              size={13}
              color={originLocated ? ORIGIN_MARK_COLOR : ORIGIN_MARK_FALLBACK_COLOR}
            />
          </span>
          <span
            className={cn(
              textVariants({ variant: "hint" }),
              "w-12 flex-none text-left group-data-[armed=true]:text-[var(--color-accent-strong)]",
            )}
          >
            {label}
          </span>
        </label>
        <input
          id={inputId}
          type="search"
          aria-label={`${label}を住所・施設で探す`}
          placeholder={armed ? armedHint : value}
          disabled={full}
          enterKeyHint="search"
          className={cn(
            "min-w-0 flex-auto rounded-sm bg-transparent px-1 py-1 text-[length:var(--font-size-sm)] text-[var(--foreground)]",
            "focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]",
            valueSet && !armed ? "placeholder:text-[var(--foreground)]" : "placeholder:text-[var(--color-muted)]",
          )}
          {...lookup.inputProps()}
          onKeyDown={(event) => {
            if (event.key === "Escape") lookup.close({ clearText: true });
          }}
          data-usage={`住所か施設の名前を入れて${label}を探します。${PREDICTION_MIN_LENGTH}文字から、打つのを止めると候補が出ます。候補を選ぶと${label}${role === "waypoint" ? "に足します" : "にします"}。`}
        />
        <Toggle
          variant="plain"
          className={
            armed
              ? "flex-none rounded-sm bg-[var(--color-accent)] px-1.5 py-1 text-[length:var(--font-size-sm)] text-[var(--color-surface)]"
              : "flex-none rounded-sm px-1.5 py-1 text-[length:var(--font-size-sm)] text-[var(--color-accent-strong)]"
          }
          pressed={armed}
          disabled={full}
          aria-label={
            full ? `${label}は上限まで置いてあります` : armed ? `${label}の指定をやめる` : `${label}を${armLabel}`
          }
          onClick={() => onArm(armed ? null : role)}
          usage={usage}
        >
          {armed ? "やめる" : full ? "上限" : armLabel}
        </Toggle>
        {extra}
      </form>

      {listing && (
        <div className="relative border-t border-[var(--color-border)] p-1 pr-8">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => lookup.close({ clearText: true })}
            aria-label={`${label}の候補を閉じる`}
            className="absolute top-1 right-1 size-6 text-[var(--foreground)]"
            usage="候補の一覧を閉じて、打った文字を消します。"
          >
            ✕
          </Button>
          <PlaceCandidates
            lookup={lookup}
            renderCandidate={(candidate, _index, candidateLabel) => (
              <Button
                variant="menu"
                size="sm"
                className="w-full"
                onClick={() => choose(candidate)}
                usage={`この候補を${label}${role === "waypoint" ? "に足します" : "にします"}。`}
              >
                {candidateLabel}
              </Button>
            )}
          />
        </div>
      )}
    </div>
  );
}

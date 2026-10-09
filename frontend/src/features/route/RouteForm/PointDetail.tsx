"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef } from "react";

import { Badge } from "@/components/ui/Badge/Badge";
import { Button } from "@/components/ui/Button/Button";
import { Toggle } from "@/components/ui/Toggle/Toggle";
import { textVariants } from "@/components/ui/Text/Text";
import PlaceCandidates, { isRepresentative } from "@/features/route/PlaceSearch/PlaceCandidates";
import { PREDICTION_MIN_LENGTH, usePlaceLookup } from "@/features/route/PlaceSearch/usePlaceLookup";
import { areaAt } from "@/features/route/placeSearchApi";
import { cn } from "@/lib/cn";
import { getQueryClient } from "@/lib/queryClient";
import type { Coordinates, PinRole, PlaceCandidate } from "@/types/route";

import PointMark from "./PointMark";

interface PointDetailProps {
  role: PinRole;
  /** 地点の呼び名（出発地／経由地2／目的地／経由地を足す）。 */
  title: string;
  /** 印に入れる字（経由地の番号。地図のピンと同じ）。 */
  markLabel?: string;
  /** どうやって置いた地点か（探して選んだ地点／地図で選んだ地点／現在地）。置いていなければ無し。 */
  source?: string;
  /** 地点の名前（探した施設・住所の名前／地図で選んだ地点／現在地／未設定）。経由地を足すときは無し。 */
  name?: string;
  /** 探して置いた地点なら、その候補（辺りと、代表の位置かを出す）。 */
  found: PlaceCandidate | null;
  /** 地点の位置。置いていない・現在地を取れていなければnull。辺りの無い地点は、ここから辺りを引いて出す。 */
  at: Coordinates | null;
  /** 地点が置いてあるか。打つ欄の誘いを「置き直す」にする。 */
  placed: boolean;
  /** 地図で置く操作の名前（地図で選ぶ／地図で追加／地図で置き直す）。 */
  armLabel: string;
  /** 地図で置く操作の右に並べる別の操作（消す・現在地に戻す）。 */
  extra?: React.ReactNode;
  /** 地図で置く状態の間に、打つ欄の中に出す文言。置いた数を隠さないため、経由地を足す間は件数を添える。 */
  armedHint?: string;
  /** 地図で置く操作の使い方の文。 */
  usage: string;
  /** 候補を選ぶと何が起きるか（「目的地にします」等）。 */
  chooseResult: string;
  /** 上限まで置いてあり、これ以上置けない（地図でも探してもの両方）。 */
  full?: boolean;
  armed: boolean;
  /** 地図で置く状態を切り替える。 */
  onArmToggle: () => void;
  /** 出発地の印を、実際の位置（現在地か置いた地点）の色で出すか。 */
  originLocated: boolean;
  /** 地図でいま見ている所の真ん中。施設の候補はここから近い順に並ぶ。 */
  mapCenter: Coordinates;
  /** 探して選んだ候補を、この地点として置く。 */
  onChoose: (candidate: PlaceCandidate) => void;
}

/**
 * 押した地点の詳しく: どの地点か・どうやって置いたか・名前・辺り（探した施設は候補の辺り、地図で選んだ地点・現在地・辺りの
 * 無い施設は位置から引いた辺り。探した住所は名前が住所なので出さない）と、住所・施設の名前を打って置き直す欄（候補は欄のすぐ下）、
 * 地図で置く操作と、消す・現在地に戻す。
 */
export default function PointDetail({
  role,
  title,
  markLabel,
  source,
  name,
  found,
  at,
  placed,
  armLabel,
  extra,
  armedHint = "地図をタップ",
  usage,
  chooseResult,
  full = false,
  armed,
  onArmToggle,
  originLocated,
  mapCenter,
  onChoose,
}: PointDetailProps) {
  const lookup = usePlaceLookup(mapCenter);
  const inputId = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const listing = lookup.query !== "";
  // 候補が出たら、打つ欄を面の上端へ送り、下の候補を面の高さいっぱいに見せる（狭い画面のシートでは、欄の下に出した候補が面の
  // 下端で切れる）。一覧は自分では高さを限らず、面のスクロールだけで読む（二重のスクロールにしない）。
  // 候補が届いて一覧が伸びたときにも送り直す（引いている間の短い一覧では、面の下端まで送り切れない）。
  const candidates = lookup.search.data;
  useEffect(() => {
    if (listing) formRef.current?.scrollIntoView({ block: "start" });
  }, [listing, candidates]);

  // 代表の位置（探した住所）は行きたい所そのものではないので、そこの辺りは引かない。
  const representative = found !== null && isRepresentative(found);
  const areaPoint = found?.area == null && !representative ? at : null;
  const placedArea = useQuery(
    {
      queryKey: ["place-area", areaPoint?.latitude, areaPoint?.longitude],
      queryFn: () => areaAt(areaPoint!),
      enabled: areaPoint !== null,
    },
    getQueryClient(),
  );
  // 引けない間・引けなかったときは辺りを出さない（名前と出どころは出ている）。
  const area = found?.area ?? (areaPoint !== null ? (placedArea.data ?? null) : null);

  function choose(candidate: PlaceCandidate) {
    onChoose(candidate);
    lookup.close({ clearText: true });
  }

  return (
    <section
      aria-label={title}
      className="group flex flex-col gap-1 rounded-sm border border-[var(--color-border)] p-1.5 data-[armed=true]:border-[var(--color-accent)] data-[armed=true]:shadow-[inset_0_0_0_1px_var(--color-accent)]"
      data-armed={armed}
    >
      <div className="flex min-w-0 items-start gap-2">
        <PointMark role={role} label={markLabel} originLocated={originLocated} className="mt-0.5" />
        <div className="min-w-0 flex-auto">
          <p
            className={cn(
              textVariants({ variant: "note" }),
              "group-data-[armed=true]:text-[var(--color-accent-strong)]",
            )}
          >
            {source === undefined ? title : `${title}・${source}`}
          </p>
          {name !== undefined && (
            <p className={cn(textVariants({ variant: "body" }), "font-bold [overflow-wrap:anywhere]")}>{name}</p>
          )}
          {(area !== null || representative) && (
            <p className="flex min-w-0 flex-wrap items-center gap-1">
              {area !== null && (
                <span className={cn(textVariants({ variant: "note" }), "[overflow-wrap:anywhere]")}>{area}</span>
              )}
              {/* 当たった範囲の中ほどの位置で、行きたい所そのものではない（ピンを直すのは地図の上）。 */}
              {representative && <Badge variant="warning">代表の位置</Badge>}
            </p>
          )}
        </div>
      </div>

      <form
        ref={formRef}
        role="search"
        className="scroll-mt-1"
        onSubmit={(event) => {
          event.preventDefault();
          lookup.submit();
        }}
      >
        <input
          id={inputId}
          type="search"
          aria-label={`${title}を住所・施設で探す`}
          placeholder={armed ? armedHint : placed ? "住所・施設で探して置き直す" : "住所・施設で探す"}
          disabled={full}
          enterKeyHint="search"
          className={cn(
            "w-full rounded-sm border border-[var(--color-border)] bg-transparent px-1.5 py-1 text-[length:var(--font-size-sm)] text-[var(--foreground)] placeholder:text-[var(--color-muted)]",
            "focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]",
          )}
          {...lookup.inputProps()}
          onKeyDown={(event) => {
            if (event.key === "Escape") lookup.close({ clearText: true });
          }}
          data-usage={`住所か施設の名前を入れて探します。${PREDICTION_MIN_LENGTH}文字から、打つのを止めると候補が出ます。候補を選ぶと${chooseResult}。`}
        />
      </form>

      {listing && (
        <div className="relative rounded-sm border border-[var(--color-border)] p-1 pr-8">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => lookup.close({ clearText: true })}
            aria-label={`${title}の候補を閉じる`}
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
                usage={`この候補を選ぶと${chooseResult}。`}
              >
                {candidateLabel}
              </Button>
            )}
          />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1">
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
            full ? `${title}は上限まで置いてあります` : armed ? `${title}の指定をやめる` : `${title}を${armLabel}`
          }
          onClick={onArmToggle}
          usage={usage}
        >
          {armed ? "やめる" : full ? "上限" : armLabel}
        </Toggle>
        {extra}
      </div>
    </section>
  );
}

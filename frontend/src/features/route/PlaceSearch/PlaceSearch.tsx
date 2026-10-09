"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button/Button";
import { Callout } from "@/components/ui/Callout/Callout";
import { cardVariants } from "@/components/ui/Card/Card";
import { Input } from "@/components/ui/Input/Input";
import { cn } from "@/lib/cn";
import { mapOverlayEdge } from "@/lib/mapOverlayEdges";
import type { Coordinates, PinRole, PlaceCandidate, RouteCandidate } from "@/types/route";

import PlaceCandidates, { isRepresentative } from "./PlaceCandidates";
import { PREDICTION_MIN_LENGTH, usePlaceLookup } from "./usePlaceLookup";

const ROLE_CHOICES: { role: PinRole; label: string; placed: string; usage: string }[] = [
  {
    role: "destination",
    label: "目的地",
    placed: "目的地にしました",
    usage: "この地点を目的地にします。周回のときは目的地へ向かうルートに切り替えます。",
  },
  { role: "origin", label: "出発地", placed: "出発地にしました", usage: "この地点から出発します。" },
  {
    role: "waypoint",
    label: "経由地",
    placed: "経由地に足しました",
    usage: "この地点を通る経由地として足します。周回のときは目的地へ向かうルートに切り替えます。",
  },
];

interface PlaceSearchProps {
  /** 地図でいま見ている所の真ん中。施設の候補はここから近い順に並び、ここからの直線距離を添える。 */
  mapCenter: Coordinates;
  /** 選んだ候補を、選んだ役割の地点として置く。 */
  onPlace: (role: PinRole, candidate: PlaceCandidate) => void;
  /** 経由地を上限まで置いてあり、もう足せない。 */
  waypointsFull: boolean;
  /** 地図に描くルート。1本以上に変わると地図がルートへ寄るので、置いたあとの案内を閉じて地図の上を空ける。 */
  routes: readonly RouteCandidate[];
}

/**
 * 住所か施設の名前で地点を探し、候補を目的地・出発地・経由地のどれかとして置く。欄は地図の上端の帯で、候補の一覧と置いたあとの案内は
 * 帯の下へ地図に重ねて出す（面の中に置くと、一覧が面の高さに縛られて地図を隠す）。
 */
export default function PlaceSearch({ mapCenter, onPlace, waypointsFull, routes }: PlaceSearchProps) {
  const lookup = usePlaceLookup(mapCenter);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [placed, setPlaced] = useState<{ candidate: PlaceCandidate; message: string } | null>(null);
  // 描いている間に閉じる（effectで閉じると、地図がルートへ寄るときに閉じる前の案内を測る）。✕と同じく一覧ごと閉じる
  // （案内だけを消すと、引いた候補の一覧が出直す）。
  const [routesSeen, setRoutesSeen] = useState(routes);
  if (routes !== routesSeen) {
    setRoutesSeen(routes);
    if (routes.length > 0 && placed !== null) close();
  }

  function startOver() {
    setSelectedIndex(null);
    setPlaced(null);
  }

  function place(candidate: PlaceCandidate, role: PinRole, message: string) {
    onPlace(role, candidate);
    setSelectedIndex(null);
    setPlaced({ candidate, message });
  }

  function close() {
    lookup.close();
    startOver();
  }

  const showingResults = lookup.query !== "" && placed === null;

  return (
    <div className="relative border-b border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5">
      <form
        className="flex max-w-xl items-center gap-2"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          if (lookup.submit()) startOver();
        }}
      >
        <Input
          type="search"
          aria-label="住所・施設で探す"
          placeholder="住所・施設で探す（例: 千代田区丸の内1-9、浅草寺）"
          className="min-w-0 flex-auto"
          {...lookup.inputProps(startOver)}
          data-usage={`住所か施設の名前を入れて探します。${PREDICTION_MIN_LENGTH}文字から、打つのを止めると続きの候補が出ます。候補を選ぶと、目的地・出発地・経由地のどれにするかを選べます。`}
        />
        <Button type="submit" size="sm" className="flex-none" usage="入れた住所・施設の名前で地点の候補を探します。">
          検索
        </Button>
      </form>

      {(showingResults || placed !== null) && (
        <div
          {...mapOverlayEdge("top", { transient: true })}
          className={cn(
            cardVariants({ variant: "float" }),
            "absolute top-full left-3 z-[var(--z-map-detail)] mt-1 flex w-[calc(100%-1.5rem)] max-w-xl max-h-[min(50vh,20rem)] flex-col gap-1 overflow-y-auto rounded-sm p-2 pr-9",
          )}
        >
          <Button
            variant="ghost"
            size="icon"
            onClick={close}
            aria-label="検索の結果を閉じる"
            className="absolute top-1.5 right-1.5 size-6 text-[var(--foreground)]"
            usage="候補の一覧と案内を閉じて、地図を空けます。"
          >
            ✕
          </Button>
          {showingResults && (
            <PlaceCandidates
              lookup={lookup}
              renderCandidate={(candidate, index, label) => {
                const selected = selectedIndex === index;
                return (
                  <>
                    <Button
                      variant="menu"
                      size="sm"
                      className="w-full"
                      aria-expanded={selected}
                      onClick={() => setSelectedIndex(selected ? null : index)}
                      usage="この候補を、目的地・出発地・経由地のどれにするかを選びます。"
                    >
                      {label}
                    </Button>
                    {selected && (
                      <div className="flex flex-wrap items-center gap-1 py-1 pl-2">
                        {ROLE_CHOICES.map(({ role, label: roleLabel, placed: message, usage }) => {
                          const full = role === "waypoint" && waypointsFull;
                          return (
                            <Button
                              key={role}
                              size="xs"
                              disabled={full}
                              aria-label={full ? `${roleLabel}は上限まで置いてあります` : undefined}
                              onClick={() => place(candidate, role, message)}
                              usage={usage}
                            >
                              {roleLabel}へ
                            </Button>
                          );
                        })}
                      </div>
                    )}
                  </>
                );
              }}
            />
          )}

          {/* 1行に収め、収まらなければ名前を省く（置いた役割と代表の位置かは省かない）。 */}
          {placed !== null && (
            <Callout
              role="status"
              tone={isRepresentative(placed.candidate) ? "warning" : "neutral"}
              className="flex min-w-0 whitespace-nowrap"
            >
              <span className="min-w-0 truncate">「{placed.candidate.name}</span>
              <span className="flex-none">
                」を{placed.message}
                {isRepresentative(placed.candidate) && "（代表の位置）"}
              </span>
            </Callout>
          )}
        </div>
      )}
    </div>
  );
}

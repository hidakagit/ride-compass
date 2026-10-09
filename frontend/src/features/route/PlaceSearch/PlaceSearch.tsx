"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge/Badge";
import { Button } from "@/components/ui/Button/Button";
import { Callout } from "@/components/ui/Callout/Callout";
import { cardVariants } from "@/components/ui/Card/Card";
import { Input } from "@/components/ui/Input/Input";
import { textVariants } from "@/components/ui/Text/Text";
import ErrorText from "@/features/route/ErrorText/ErrorText";
import { haversineKm } from "@/features/route/geoDistance";
import { searchPlaces } from "@/features/route/placeSearchApi";
import { cn } from "@/lib/cn";
import { mapOverlayEdge } from "@/lib/mapOverlayEdges";
import { getQueryClient } from "@/lib/queryClient";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { vocabulary } from "@/types/generated/vocabulary";
import type { Coordinates, PinRole, PlaceCandidate, RouteCandidate } from "@/types/route";

// 種類と段の名前はbackendの語彙（生成物）から読む。種類を足しても行の形は変わらない。
const KIND_LABELS = Object.fromEntries(vocabulary.placeKinds.map((k) => [k.key, k.label])) as Record<
  PlaceCandidate["kind"],
  string
>;
const LEVEL_LABELS = Object.fromEntries(vocabulary.placeMatchLevels.map((l) => [l.key, l.label])) as Record<
  PlaceCandidate["level"],
  string
>;
// 打ちかけで引き始める長さ（空白を除いた文字数）と、打つのが止まってから引くまでの間。口の回数制限はこの間から決まる。
const PREDICTION_MIN_LENGTH = routeGenerateConfig.place_prediction_min_length;
const PREDICTION_DELAY_MS = routeGenerateConfig.place_prediction_delay_seconds * 1000;
// 住所は区画（都道府県から字・丁目まで）の代表の位置にすぎず、行きたい所から離れうる。施設（`point`）はその施設の位置。
const PRECISE_LEVELS: ReadonlySet<PlaceCandidate["level"]> = new Set(["point"]);

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
  onPlace: (role: PinRole, point: Coordinates) => void;
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
  const [text, setText] = useState("");
  // 引いた文字列と、引いたときの地図の真ん中。打つのが止まってから引く（打つたびに引くと口の回数制限に当たる）。
  // 引いたあとに地図を動かしても引き直さない（選んでいる最中に並びと距離が変わらない）。
  const [query, setQuery] = useState("");
  const [near, setNear] = useState(mapCenter);
  const lookUpTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [placed, setPlaced] = useState<{ candidate: PlaceCandidate; message: string } | null>(null);
  // 描いている間に閉じる（effectで閉じると、地図がルートへ寄るときに閉じる前の案内を測る）。✕と同じく一覧ごと閉じる
  // （案内だけを消すと、引いた候補の一覧が出直す）。
  const [routesSeen, setRoutesSeen] = useState(routes);
  if (routes !== routesSeen) {
    setRoutesSeen(routes);
    if (routes.length > 0 && placed !== null) close();
  }

  const search = useQuery(
    {
      queryKey: ["place-search", query, near.latitude, near.longitude],
      queryFn: () => searchPlaces(query, near),
      enabled: query !== "",
      // 打ちかけで引き直す間も、前の候補を出しておく（一覧が「探しています…」と入れ替わってちらつかない）。
      placeholderData: keepPreviousData,
    },
    getQueryClient(),
  );

  useEffect(() => () => clearTimeout(lookUpTimer.current), []);

  function lookUp(trimmed: string) {
    setSelectedIndex(null);
    setPlaced(null);
    setQuery(trimmed);
    setNear(mapCenter);
  }

  // かな漢字の変換中は呼ばない（変換を確定したときに呼ぶ）。
  function scheduleLookUp(value: string) {
    clearTimeout(lookUpTimer.current);
    if (value.replace(/\s/g, "").length < PREDICTION_MIN_LENGTH) return;
    const trimmed = value.trim();
    lookUpTimer.current = setTimeout(() => lookUp(trimmed), PREDICTION_DELAY_MS);
  }

  function submit() {
    clearTimeout(lookUpTimer.current);
    const trimmed = text.trim();
    if (trimmed === "") return;
    lookUp(trimmed);
    if (trimmed === query && near === mapCenter) void search.refetch();
  }

  function place(candidate: PlaceCandidate, role: PinRole, message: string) {
    onPlace(role, { latitude: candidate.latitude, longitude: candidate.longitude });
    setSelectedIndex(null);
    setPlaced({ candidate, message });
  }

  function close() {
    setQuery("");
    setSelectedIndex(null);
    setPlaced(null);
  }

  const candidates = search.data ?? [];
  const showingResults = query !== "" && placed === null;

  return (
    <div className="relative border-b border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5">
      <form
        className="flex max-w-xl items-center gap-2"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Input
          type="search"
          aria-label="住所・施設で探す"
          placeholder="住所・施設で探す（例: 千代田区丸の内1-9、浅草寺）"
          className="min-w-0 flex-auto"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            if (!(event.nativeEvent as InputEvent).isComposing) scheduleLookUp(event.target.value);
          }}
          onCompositionEnd={(event) => scheduleLookUp(event.currentTarget.value)}
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
          {showingResults &&
            (search.isFetching && !search.isPlaceholderData ? (
              <p role="status" className={textVariants({ variant: "hint" })}>
                探しています…
              </p>
            ) : search.isError ? (
              <ErrorText>{search.error.message}</ErrorText>
            ) : candidates.length === 0 ? (
              <p role="status" className={textVariants({ variant: "hint" })}>
                当たる住所・施設がありません。
              </p>
            ) : (
              <ul aria-label="地点の候補" className="flex flex-col gap-0.5">
                {candidates.map((candidate, index) => {
                  const selected = selectedIndex === index;
                  return (
                    <li key={`${candidate.name}:${candidate.latitude}:${candidate.longitude}`}>
                      <Button
                        variant="menu"
                        size="sm"
                        className="w-full"
                        aria-expanded={selected}
                        onClick={() => setSelectedIndex(selected ? null : index)}
                        usage="この候補を、目的地・出発地・経由地のどれにするかを選びます。"
                      >
                        <span className="min-w-0 flex-auto truncate">
                          {candidate.name}
                          {/* 施設の辺り。同じ名前のチェーンの店を見分ける。名前より控えめにし、狭い幅では先に切れる。 */}
                          {candidate.area !== null && (
                            <span className={cn("ml-1.5", textVariants({ variant: "note" }))}>{candidate.area}</span>
                          )}
                        </span>
                        {candidate.kind === "facility" && (
                          <span className="flex-none tabular-nums">{haversineKm(near, candidate).toFixed(1)}km</span>
                        )}
                        <Badge>{KIND_LABELS[candidate.kind]}</Badge>
                        <Badge variant="outline">{LEVEL_LABELS[candidate.level]}</Badge>
                      </Button>
                      {selected && (
                        <div className="flex flex-wrap items-center gap-1 py-1 pl-2">
                          {ROLE_CHOICES.map(({ role, label, placed: message, usage }) => {
                            const full = role === "waypoint" && waypointsFull;
                            return (
                              <Button
                                key={role}
                                size="xs"
                                disabled={full}
                                aria-label={full ? `${label}は上限まで置いてあります` : undefined}
                                onClick={() => place(candidate, role, message)}
                                usage={usage}
                              >
                                {label}へ
                              </Button>
                            );
                          })}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            ))}

          {/* 1行に収め、収まらなければ名前を省く（置いた役割と代表の位置かは省かない）。 */}
          {placed !== null && (
            <Callout
              role="status"
              tone={PRECISE_LEVELS.has(placed.candidate.level) ? "neutral" : "warning"}
              className="flex min-w-0 whitespace-nowrap"
            >
              <span className="min-w-0 truncate">「{placed.candidate.name}</span>
              <span className="flex-none">
                」を{placed.message}
                {!PRECISE_LEVELS.has(placed.candidate.level) && "（代表の位置）"}
              </span>
            </Callout>
          )}
        </div>
      )}
    </div>
  );
}

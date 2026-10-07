"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge/Badge";
import { Button } from "@/components/ui/Button/Button";
import { Callout } from "@/components/ui/Callout/Callout";
import { Input } from "@/components/ui/Input/Input";
import { textVariants } from "@/components/ui/Text/Text";
import ErrorText from "@/features/route/ErrorText/ErrorText";
import { searchPlaces } from "@/features/route/placeSearchApi";
import { getQueryClient } from "@/lib/queryClient";
import { vocabulary } from "@/types/generated/vocabulary";
import type { Coordinates, PinRole, PlaceCandidate } from "@/types/route";

// 種類と段の名前はbackendの語彙（生成物）から読む。種類を足しても行の形は変わらない。
const KIND_LABELS = Object.fromEntries(vocabulary.placeKinds.map((k) => [k.key, k.label])) as Record<
  PlaceCandidate["kind"],
  string
>;
const LEVEL_LABELS = Object.fromEntries(vocabulary.placeMatchLevels.map((l) => [l.key, l.label])) as Record<
  PlaceCandidate["level"],
  string
>;
// 街区より粗い段で当たった地点は、その範囲の代表の位置にすぎず、行きたい所から離れうる。
const PRECISE_LEVELS: ReadonlySet<PlaceCandidate["level"]> = new Set(["block", "building"]);

const ROLE_CHOICES: { role: PinRole; label: string; placed: string; usage: string }[] = [
  { role: "origin", label: "出発地", placed: "出発地にしました", usage: "この地点から出発します。" },
  {
    role: "waypoint",
    label: "経由地",
    placed: "経由地に足しました",
    usage: "この地点を通る経由地として足します。周回のときは目的地へ向かうルートに切り替えます。",
  },
  {
    role: "destination",
    label: "目的地",
    placed: "目的地にしました",
    usage: "この地点を目的地にします。周回のときは目的地へ向かうルートに切り替えます。",
  },
];

interface PlaceSearchProps {
  /** 選んだ候補を、選んだ役割の地点として置く。 */
  onPlace: (role: PinRole, point: Coordinates) => void;
  /** 経由地を上限まで置いてあり、もう足せない。 */
  waypointsFull: boolean;
}

/** 住所で地点を探し、候補を出発地・経由地・目的地のどれかとして置く。 */
export default function PlaceSearch({ onPlace, waypointsFull }: PlaceSearchProps) {
  const [text, setText] = useState("");
  // 引いた文字列。打つたびには引かない（口の回数制限に当たる）。
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [placed, setPlaced] = useState<{ candidate: PlaceCandidate; message: string } | null>(null);

  const search = useQuery(
    {
      queryKey: ["place-search", query],
      queryFn: () => searchPlaces(query),
      enabled: query !== "",
    },
    getQueryClient(),
  );

  function submit() {
    const trimmed = text.trim();
    if (trimmed === "") return;
    setSelectedIndex(null);
    setPlaced(null);
    if (trimmed === query) void search.refetch();
    else setQuery(trimmed);
  }

  function place(candidate: PlaceCandidate, role: PinRole, message: string) {
    onPlace(role, { latitude: candidate.latitude, longitude: candidate.longitude });
    setSelectedIndex(null);
    setPlaced({ candidate, message });
  }

  const candidates = search.data ?? [];

  return (
    <div className="flex flex-col gap-1">
      <form
        className="flex items-center gap-2"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Input
          type="search"
          aria-label="住所で探す"
          placeholder="住所で探す（例: 千代田区丸の内1-9）"
          className="min-w-0 flex-auto"
          value={text}
          onChange={(event) => setText(event.target.value)}
          data-usage="住所を入れて探します。候補を選ぶと、出発地・経由地・目的地のどれにするかを選べます。"
        />
        <Button type="submit" size="sm" className="flex-none" usage="入れた住所で地点の候補を探します。">
          検索
        </Button>
      </form>

      {query !== "" && placed === null && (
        <>
          {search.isFetching ? (
            <p role="status" className={textVariants({ variant: "hint" })}>
              探しています…
            </p>
          ) : search.isError ? (
            <ErrorText>{search.error.message}</ErrorText>
          ) : candidates.length === 0 ? (
            <p role="status" className={textVariants({ variant: "hint" })}>
              当たる住所がありません。
            </p>
          ) : (
            <ul aria-label="住所の候補" className="flex max-h-60 flex-col gap-0.5 overflow-y-auto">
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
                      usage="この候補を、出発地・経由地・目的地のどれにするかを選びます。"
                    >
                      <span className="min-w-0 flex-auto truncate">{candidate.name}</span>
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
                              aria-label={full ? `${label}は上限まで置いてあります` : `${label}にする`}
                              onClick={() => place(candidate, role, message)}
                              usage={usage}
                            >
                              {label}
                            </Button>
                          );
                        })}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}

      {placed !== null && (
        <Callout role="status" tone={PRECISE_LEVELS.has(placed.candidate.level) ? "neutral" : "warning"}>
          「{placed.candidate.name}」を{placed.message}。
          {PRECISE_LEVELS.has(placed.candidate.level)
            ? "地図のピンをつかんで動かすと直せます。"
            : `当たったのは「${LEVEL_LABELS[placed.candidate.level]}」までなので、ピンはその範囲の代表の位置です。地図のピンをつかんで、行きたい所へ動かしてください。`}
        </Callout>
      )}
    </div>
  );
}

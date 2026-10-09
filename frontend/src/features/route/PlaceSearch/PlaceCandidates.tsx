"use client";

import { Badge } from "@/components/ui/Badge/Badge";
import { textVariants } from "@/components/ui/Text/Text";
import ErrorText from "@/features/route/ErrorText/ErrorText";
import { haversineKm } from "@/features/route/geoDistance";
import { cn } from "@/lib/cn";
import { vocabulary } from "@/types/generated/vocabulary";
import type { PlaceCandidate } from "@/types/route";

import type { usePlaceLookup } from "./usePlaceLookup";

// 種類と段の名前はbackendの語彙（生成物）から読む。種類を足しても行の形は変わらない。
const KIND_LABELS = Object.fromEntries(vocabulary.placeKinds.map((k) => [k.key, k.label])) as Record<
  PlaceCandidate["kind"],
  string
>;
const LEVEL_LABELS = Object.fromEntries(vocabulary.placeMatchLevels.map((l) => [l.key, l.label])) as Record<
  PlaceCandidate["level"],
  string
>;
// 街区より粗い段で当たった地点は、その範囲の代表の位置にすぎず、行きたい所から離れうる。施設はその施設の位置。
const PRECISE_LEVELS: ReadonlySet<PlaceCandidate["level"]> = new Set(["block", "building", "point"]);

/** 置いた地点が、当たった範囲の代表の位置にすぎないか。 */
function isRepresentative(candidate: PlaceCandidate): boolean {
  return !PRECISE_LEVELS.has(candidate.level);
}

/** 置いた地点の行に出す名前。代表の位置なら、そう添える（ピンは行きたい所から離れうる）。 */
export function placedName(candidate: PlaceCandidate): string {
  return isRepresentative(candidate) ? `${candidate.name}（代表の位置）` : candidate.name;
}

interface PlaceCandidatesProps {
  lookup: ReturnType<typeof usePlaceLookup>;
  /** 候補1件の行。中身（名前・辺り・距離・札）は`label`で渡す。 */
  renderCandidate: (candidate: PlaceCandidate, index: number, label: React.ReactNode) => React.ReactNode;
}

/** 引いた候補の一覧。引いている間・引けない・当たらないときは、その文を出す。 */
export default function PlaceCandidates({ lookup, renderCandidate }: PlaceCandidatesProps) {
  const { search, near } = lookup;
  if (search.isFetching && !search.isPlaceholderData) {
    return (
      <p role="status" className={textVariants({ variant: "hint" })}>
        探しています…
      </p>
    );
  }
  if (search.isError) return <ErrorText>{search.error.message}</ErrorText>;
  const candidates = search.data ?? [];
  if (candidates.length === 0) {
    return (
      <p role="status" className={textVariants({ variant: "hint" })}>
        当たる住所・施設がありません。
      </p>
    );
  }
  return (
    <ul aria-label="地点の候補" className="flex flex-col gap-0.5">
      {candidates.map((candidate, index) => (
        <li key={`${candidate.name}:${candidate.latitude}:${candidate.longitude}`}>
          {renderCandidate(
            candidate,
            index,
            <>
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
            </>,
          )}
        </li>
      ))}
    </ul>
  );
}

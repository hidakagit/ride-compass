"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge/Badge";
import { Button } from "@/components/ui/Button/Button";
import { DialogContent, DialogRoot } from "@/components/ui/Dialog/Dialog";
import { SavedPlaceIcon, SavePlaceIcon } from "@/components/ui/icons/icons";
import { Input } from "@/components/ui/Input/Input";
import { Toggle } from "@/components/ui/Toggle/Toggle";
import { textVariants } from "@/components/ui/Text/Text";
import PlaceCandidates, { isRepresentative } from "@/features/route/PlaceSearch/PlaceCandidates";
import { PREDICTION_MIN_LENGTH, usePlaceLookup } from "@/features/route/PlaceSearch/usePlaceLookup";
import { areaAt } from "@/features/route/placeSearchApi";
import { savedPlaceAt, savedPlacesMatching } from "@/features/route/savedPlaces";
import type { SavedPlacesState } from "@/features/route/useSavedPlaces";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useVisualViewport } from "@/hooks/useVisualViewport";
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
  /** どうやって置いた地点か（探して選んだ地点／地図で選んだ地点）。置いていない・現在地なら無し（名前が現在地と言う）。 */
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
  /** 探して選んだ候補（保存した地点も）を、この地点として置く。 */
  onChoose: (candidate: PlaceCandidate) => void;
  /** 保存した地点の一覧と保存・削除。打つ欄を押すと候補に出し、置いた地点を保存する。 */
  savedPlaces: SavedPlacesState;
}

/** 打つ欄を、いちばん近い縦にスクロールする祖先の上端（欄の`scroll-margin-top`を空ける）へ送る。`scrollIntoView`は祖先を
 * 全部送るので、ページまで送って地図の上側を切る。 */
function scrollToScrollerTop(element: HTMLElement) {
  for (let scroller = element.parentElement; scroller !== null; scroller = scroller.parentElement) {
    if (!/auto|scroll/.test(getComputedStyle(scroller).overflowY)) continue;
    const margin = parseFloat(getComputedStyle(element).scrollMarginTop) || 0;
    scroller.scrollTop += element.getBoundingClientRect().top - scroller.getBoundingClientRect().top - margin;
    return;
  }
}

/**
 * 押した地点の詳しく: どの地点か・どうやって置いたか・名前・辺り（探した施設は候補の辺り、地図で選んだ地点・現在地・辺りの
 * 無い施設は位置から引いた辺り。探した住所は名前が住所なので出さない）と、住所・施設の名前を打って置き直す欄（候補は欄のすぐ下。
 * 欄を押すと、保存した地点のうち打った文字を名前に含むものを住所・施設の候補の上に出す。狭い画面では、欄を押してから選ぶ・閉じる
 * までは欄と候補を見えている範囲の上側に出す）、地図で置く操作と、消す・現在地に戻す・置いた地点の保存（保存した地点なら保存をやめる）。
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
  savedPlaces,
}: PointDetailProps) {
  const lookup = usePlaceLookup(mapCenter);
  const inputId = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const listing = lookup.query !== "";
  // 打つ欄を押してから、選ぶ・閉じるまでの間は、保存した地点を候補に出す。
  const [browsing, setBrowsing] = useState(false);
  const inputProps = lookup.inputProps();
  const savedMatches = browsing ? savedPlacesMatching(savedPlaces.places, inputProps.value) : [];
  const listOpen = listing || savedMatches.length > 0;
  // 狭い画面では、欄を押してから選ぶ・閉じるまでは、欄と候補を見えている範囲（キーボードの上まで）の上側に重ねて出し、候補は
  // その中で送る。シートの中では、欄の下の候補がシートの下端とキーボードの裏に入る。出す物の有無で上げ下げすると、打つ途中で
  // 欄が上側とシートを行き来してちらつく。欄は同じ要素のまま動かす（作り直すとキーボードが閉じる）。
  const isMobile = useIsMobile();
  const raised = isMobile && browsing;
  const visible = useVisualViewport(raised);
  // 広い画面では、候補が出たら打つ欄をパネルの上端へ送り、下の候補をパネルの高さいっぱいに見せる。一覧は自分では高さを限らず、
  // パネルのスクロールだけで読む（二重のスクロールにしない）。候補が届いて一覧が伸びたときにも送り直す（引いている間の短い一覧
  // では、パネルの下端まで送り切れない）。
  const candidates = lookup.search.data;
  useEffect(() => {
    if (listOpen && !isMobile && formRef.current !== null) scrollToScrollerTop(formRef.current);
  }, [listOpen, isMobile, candidates]);

  // 探した住所は名前が辺りを含み、代表の位置なら行きたい所そのものでもないので、辺りは引かない。
  const representative = found !== null && isRepresentative(found);
  const areaPoint = found?.kind !== "address" && found?.area == null ? at : null;
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

  function closeList() {
    lookup.close({ clearText: true });
    setBrowsing(false);
  }

  function choose(candidate: PlaceCandidate) {
    onChoose(candidate);
    closeList();
  }

  // 置いた地点の保存。名前の欄には、探して置いた候補の名前か辺り（地図で選んだ地点・現在地は辺りのほうが見分けやすい）を入れておく。
  const savedHere = at !== null ? savedPlaceAt(savedPlaces.places, at) : null;
  const suggestedPlaceName = found?.name ?? area ?? name ?? title;
  const [naming, setNaming] = useState(false);
  // 手で書き換えるまでは、上の仮の名前を出す（空にして保存しても仮の名前）。
  const [placeNameDraft, setPlaceNameDraft] = useState<string | null>(null);
  const placeName = placeNameDraft?.trim() || suggestedPlaceName;
  const overwritingPlace = savedPlaces.places.some((place) => place.name === placeName);

  function savePlace() {
    if (at === null) return;
    // 地図で選んだ地点・現在地は、その位置そのもの（施設と同じく代表の位置ではない）として持つ。
    const { kind, level } = found ?? { kind: "facility" as const, level: "point" as const };
    savedPlaces.save({ kind, level, name: placeName, area, latitude: at.latitude, longitude: at.longitude });
    setNaming(false);
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
          {/* 呼び名・名前・出どころを1行に並べ、入らなければ折り返す。出どころが名前と同じ（地図で選んだ地点）なら重ねて出さない。 */}
          <p className="flex min-w-0 flex-wrap items-baseline gap-x-1.5">
            <span
              className={cn(
                textVariants({ variant: "note" }),
                "group-data-[armed=true]:text-[var(--color-accent-strong)]",
              )}
            >
              {title}
            </span>
            {name !== undefined && (
              <span className={cn(textVariants({ variant: "body" }), "font-bold [overflow-wrap:anywhere]")}>
                {name}
              </span>
            )}
            {source !== undefined && source !== name && (
              <span className={textVariants({ variant: "note" })}>{source}</span>
            )}
          </p>
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

      <div
        className={cn(
          "flex flex-col gap-1",
          raised && "fixed inset-x-0 top-0 bottom-0 z-10 bg-[var(--background)] p-2 shadow-[0_2px_8px_rgba(0,0,0,0.2)]",
        )}
        style={raised && visible !== null ? { top: visible.top, bottom: "auto", height: visible.height } : undefined}
      >
        {raised && <p className={textVariants({ variant: "heading" })}>{title}を探す</p>}
        {/* 打つ欄と地図で置く操作・消す等を1行に並べ、入らなければ操作を次の行へ送る。上側に出している間は欄だけにする。 */}
        <div className="flex flex-wrap items-center gap-1">
          <form
            ref={formRef}
            role="search"
            className="min-w-[9rem] flex-1 scroll-mt-1"
            onSubmit={(event) => {
              event.preventDefault();
              lookup.submit();
            }}
          >
            <input
              id={inputId}
              type="search"
              aria-label={`${title}を住所・施設で探す`}
              placeholder={armed ? armedHint : placed ? "住所・施設で置き直す" : "住所・施設で探す"}
              disabled={full}
              enterKeyHint="search"
              className={cn(
                "w-full rounded-sm border border-[var(--color-border)] bg-transparent px-1.5 py-1 text-[length:var(--font-size-sm)] text-[var(--foreground)] placeholder:text-[var(--color-muted)]",
                "focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]",
              )}
              {...inputProps}
              onFocus={() => setBrowsing(true)}
              onKeyDown={(event) => {
                if (event.key === "Escape") closeList();
              }}
              data-usage={`住所か施設の名前を入れて探します。${PREDICTION_MIN_LENGTH}文字から、打つのを止めると候補が出ます。候補を選ぶと${chooseResult}。`}
            />
          </form>
          <div className={raised ? "hidden" : "contents"}>
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
            {at !== null &&
              (savedHere !== null ? (
                <Button
                  size="panelIcon"
                  className="ml-auto flex-none"
                  aria-label={`「${savedHere.name}」の保存をやめる`}
                  onClick={() => savedPlaces.remove(savedHere)}
                  usage="保存した地点から外します。置いた地点はそのまま残ります。"
                >
                  <SavedPlaceIcon />
                </Button>
              ) : (
                <Button
                  size="panelIcon"
                  className="ml-auto flex-none"
                  aria-label="地点を保存"
                  aria-haspopup="dialog"
                  aria-expanded={naming}
                  onClick={() => {
                    setPlaceNameDraft(null);
                    setNaming(true);
                  }}
                  usage="この地点に名前を付けてこの端末に保存します。保存した地点は、地点の打つ欄を押すと候補に出ます。"
                >
                  <SavePlaceIcon />
                </Button>
              ))}
          </div>
        </div>

        {(listOpen || raised) && (
          <div
            className={cn(
              "relative flex rounded-sm border border-[var(--color-border)] p-1 pr-8",
              raised && "min-h-0 flex-auto",
            )}
          >
            <Button
              variant="ghost"
              size="icon"
              onClick={closeList}
              aria-label={`${title}の候補を閉じる`}
              className="absolute top-1 right-1 size-6 text-[var(--foreground)]"
              usage="候補の一覧を閉じて、打った文字を消します。"
            >
              ✕
            </Button>
            <div className={cn("flex min-w-0 flex-auto flex-col gap-1", raised && "overflow-y-auto")}>
              {savedMatches.length > 0 && (
                <ul aria-label="保存した地点" className="flex flex-col gap-0.5">
                  {savedMatches.map((place) => (
                    <li key={place.name}>
                      <Button
                        variant="menu"
                        size="sm"
                        className="w-full whitespace-normal"
                        onClick={() => choose(place)}
                        usage={`保存した地点です。選ぶと${chooseResult}。`}
                      >
                        <SavedPlaceIcon size={14} />
                        <span className="min-w-0 flex-auto [overflow-wrap:anywhere]">
                          {place.name}
                          {place.area !== null && (
                            <span className={cn("ml-1.5", textVariants({ variant: "note" }))}>{place.area}</span>
                          )}
                        </span>
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              {listing && (
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
              )}
              {!listOpen && (
                <p className={textVariants({ variant: "hint" })}>
                  住所か施設の名前を{PREDICTION_MIN_LENGTH}文字から打つと、候補が出ます。
                </p>
              )}
            </div>
          </div>
        )}
      </div>
      <DialogRoot open={naming} onOpenChange={setNaming}>
        <DialogContent title="地点を保存">
          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              savePlace();
            }}
          >
            <Input
              aria-label="保存する地点の名前"
              className="min-w-0 flex-auto"
              value={placeNameDraft ?? suggestedPlaceName}
              onChange={(event) => setPlaceNameDraft(event.target.value)}
            />
            <Button type="submit" size="sm" className="flex-none">
              {overwritingPlace ? "上書き保存" : "保存"}
            </Button>
          </form>
        </DialogContent>
      </DialogRoot>
    </section>
  );
}

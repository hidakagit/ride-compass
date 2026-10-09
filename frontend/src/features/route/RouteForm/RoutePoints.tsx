"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button/Button";
import { ClearPointsIcon } from "@/components/ui/icons/icons";
import type { GenerationConditionsState } from "@/features/route/useGenerationConditions";
import type { SavedPlacesState } from "@/features/route/useSavedPlaces";
import { cn } from "@/lib/cn";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { Coordinates, PinRole, PlaceCandidate } from "@/types/route";

import PointDetail from "./PointDetail";
import PointMark from "./PointMark";

/** 押して詳しくを出す地点。経由地の`index`が無いのは、新しく足す経由地。 */
type PointTarget = { role: "origin" } | { role: "destination" } | { role: "waypoint"; index: number | null };

type RoutePointsConditions = Pick<
  GenerationConditionsState,
  | "routeMode"
  | "waypoints"
  | "removeWaypoint"
  | "destination"
  | "clearDestination"
  | "clearPoints"
  | "armedPinRole"
  | "waypointToReplace"
  | "armPinRole"
  | "foundAt"
>;

interface RoutePointsProps {
  conditions: RoutePointsConditions;
  /** 出発地の位置（現在地か、地図で置いた地点）。 */
  origin: Coordinates;
  /** 出発地を地図で置き直してあるか（falseなら現在地のまま）。 */
  originManual: boolean;
  /** 出発地が実際の位置か（現在地を取れたか、地図で置いたか）。falseの間は地図のピンと同じく印を灰色にし、
   * 名前も「現在地」と出さない（位置が仮の地点のままであることを、パネルと地図で示す）。 */
  originLocated: boolean;
  /** 出発地を現在地へ戻す（現在地の取得もこの操作が兼ねる）。 */
  onOriginReset: () => void;
  /** 出発地が、探して置いたときの位置のままなら、その候補。 */
  originFound: PlaceCandidate | null;
  /** 地図でいま見ている所の真ん中。探す施設の候補は、ここから近い順に並ぶ。 */
  mapCenter: Coordinates;
  /** 探して選んだ候補を、その役割の地点として置く（経由地は`waypointIndex`番目を置き直し、無ければ足す）。 */
  onPlaceFound: (role: PinRole, candidate: PlaceCandidate, waypointIndex: number | null) => void;
  /** 保存した地点（詳しくの打つ欄の候補と、置いた地点の保存）。 */
  savedPlaces: SavedPlacesState;
}

const MAX_WAYPOINTS = routeGenerateConfig.max_waypoints;
/** 札の印と名前の間（札の`gap-1`）。 */
const NAME_GAP_PX = 4;

/** どうやって置いた地点か。 */
function sourceOf(found: PlaceCandidate | null): string {
  return found !== null ? "探して選んだ地点" : "地図で選んだ地点";
}

/**
 * 出発地・経由地・目的地。目的地モードでは「出発地 › ①②③… ＋ › 目的地」を1行に並べ（経由地は地図のピンと同じ番号の丸。
 * 経由地が増えても出発地と目的地が欠けず、スクロールも要らない）、押した地点の詳しくを下に出す。周回は出発地の詳しくだけを出す。
 */
export default function RoutePoints({
  conditions,
  origin,
  originManual,
  originLocated,
  onOriginReset,
  originFound,
  mapCenter,
  onPlaceFound,
  savedPlaces,
}: RoutePointsProps) {
  const {
    routeMode,
    waypoints,
    removeWaypoint,
    destination,
    clearDestination,
    clearPoints,
    armedPinRole,
    waypointToReplace,
    armPinRole,
    foundAt,
  } = conditions;
  const [chosen, setChosen] = useState<PointTarget | null>(null);
  const waypointCount = waypoints.length;

  // 地図で置く状態の地点を見せる（目的地モードへ入ったときに目的地を置ける状態にする等、押さずに武装することがある）。
  // 何も押していない・押した経由地が消えた間は目的地。
  function shown(): PointTarget {
    if (routeMode === "loop") return { role: "origin" };
    if (armedPinRole === "waypoint") return { role: "waypoint", index: waypointToReplace };
    if (armedPinRole !== null) return { role: armedPinRole };
    if (chosen === null || (chosen.role === "waypoint" && chosen.index !== null && chosen.index >= waypointCount)) {
      return { role: "destination" };
    }
    return chosen;
  }
  const target = shown();
  const isShown = (other: PointTarget) =>
    other.role === "waypoint" ? target.role === "waypoint" && target.index === other.index : other.role === target.role;

  // 別の地点を押したら、地図で置く状態は解く（見えていない地点が次のタップで置かれる）。新しい経由地を押したら、地図で足せる
  // 状態にする（続けて何地点も足すのが普通の使い方）。
  function select(next: PointTarget) {
    setChosen(next);
    if (next.role === "waypoint" && next.index === null) armPinRole("waypoint");
    else if (armedPinRole !== null) armPinRole(null);
  }

  const originName =
    originFound?.name ?? (originManual ? "地図で選んだ地点" : originLocated ? "現在地" : "現在地を取得できていません");
  const destinationFound = foundAt(destination);
  const destinationName = destinationFound?.name ?? (destination !== null ? "地図で選んだ地点" : "未設定");

  // 両端の札に名前を出すか。並び全体が1行に入りきるときだけ出し、入らなければ両端とも印だけにする（途中で切った名前は読めない。
  // 名前は押すと詳しくに出る）。出さない間も名前は札の中で幅を測れる形で置いてあり、出したときの幅を足して入りきるかを見る。
  const stripRef = useRef<HTMLDivElement>(null);
  const [namesShown, setNamesShown] = useState(true);
  useLayoutEffect(() => {
    const strip = stripRef.current;
    if (strip === null) return;
    const fit = () => {
      // 並べた中身の幅は、最後の札の右端まで（`scrollWidth`は箱の幅より小さくならず、空きを測れない）。
      const used = (strip.lastElementChild?.getBoundingClientRect().right ?? 0) - strip.getBoundingClientRect().left;
      if (namesShown) {
        setNamesShown(used <= strip.clientWidth);
        return;
      }
      const names = [...strip.querySelectorAll<HTMLElement>("[data-chip-name]")].reduce(
        (sum, name) => sum + name.getBoundingClientRect().width + NAME_GAP_PX,
        0,
      );
      // 戻すときは1px余らせる（端数の丸めで、出す・出さないを行き来し続けない）。
      setNamesShown(used + names <= strip.clientWidth - 1);
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(strip);
    return () => observer.disconnect();
  }, [namesShown, originName, destinationName, waypointCount, routeMode]);

  function renderDetail() {
    const common = { originLocated, mapCenter, savedPlaces };
    if (target.role === "origin") {
      return (
        <PointDetail
          {...common}
          role="origin"
          title="出発地"
          source={originManual ? sourceOf(originFound) : undefined}
          name={originName}
          found={originFound}
          at={originLocated ? origin : null}
          placed
          armLabel="地図で選ぶ"
          extra={
            originManual ? (
              <Button
                size="xs"
                aria-label="出発地を現在地に戻す"
                onClick={onOriginReset}
                usage="地図で置いた出発地をやめて、現在地から出発します。"
              >
                現在地に戻す
              </Button>
            ) : undefined
          }
          usage="押してから地図をタップすると、そこを出発地にします。もう一度押すとやめます。"
          chooseResult="出発地にします"
          armed={armedPinRole === "origin"}
          onArmToggle={() => armPinRole(armedPinRole === "origin" ? null : "origin")}
          onChoose={(candidate) => onPlaceFound("origin", candidate, null)}
        />
      );
    }
    if (target.role === "destination") {
      const set = destination !== null;
      return (
        <PointDetail
          {...common}
          role="destination"
          title="目的地"
          source={set ? sourceOf(destinationFound) : undefined}
          name={destinationName}
          found={destinationFound}
          at={destination}
          placed={set}
          armLabel={set ? "地図で置き直す" : "地図で選ぶ"}
          extra={
            set ? (
              <Button size="xs" variant="ghost" aria-label="目的地を消す" onClick={clearDestination}>
                ✕ 消す
              </Button>
            ) : undefined
          }
          usage="押してから地図をタップすると、そこを目的地にします。もう一度押すとやめます。"
          chooseResult="目的地にします"
          armed={armedPinRole === "destination"}
          onArmToggle={() => armPinRole(armedPinRole === "destination" ? null : "destination")}
          onChoose={(candidate) => onPlaceFound("destination", candidate, null)}
        />
      );
    }
    const { index } = target;
    if (index === null) {
      const armed = armedPinRole === "waypoint";
      return (
        <PointDetail
          {...common}
          role="waypoint"
          title="新しい経由地"
          found={null}
          at={null}
          placed={false}
          armLabel="地図で追加"
          armedHint={waypointCount > 0 ? `地図をタップ[${waypointCount}地点]` : "地図をタップ"}
          usage="押してから地図をタップするたびに、そこを通る経由地を足します。もう一度押すとやめます。"
          chooseResult="経由地に足します"
          full={waypointCount >= MAX_WAYPOINTS}
          armed={armed}
          onArmToggle={() => armPinRole(armed ? null : "waypoint")}
          onChoose={(candidate) => {
            onPlaceFound("waypoint", candidate, null);
            // 足した経由地の詳しくを出す（どこに置いたかを確かめられる）。
            setChosen({ role: "waypoint", index: waypointCount });
          }}
        />
      );
    }
    const title = `経由地${index + 1}`;
    const found = foundAt(waypoints[index]);
    const armed = armedPinRole === "waypoint" && waypointToReplace === index;
    return (
      <PointDetail
        {...common}
        role="waypoint"
        title={title}
        markLabel={String(index + 1)}
        source={sourceOf(found)}
        name={found?.name ?? "地図で選んだ地点"}
        found={found}
        at={waypoints[index]}
        placed
        armLabel="地図で置き直す"
        extra={
          <Button
            size="xs"
            variant="ghost"
            aria-label={`${title}を消す`}
            onClick={() => {
              removeWaypoint(index);
              setChosen(null);
            }}
          >
            ✕ 消す
          </Button>
        }
        usage={`押してから地図をタップすると、${title}をそこへ置き直します。もう一度押すとやめます。`}
        chooseResult={`${title}を置き直します`}
        armed={armed}
        onArmToggle={() => armPinRole(armed ? null : "waypoint", armed ? null : index)}
        onChoose={(candidate) => onPlaceFound("waypoint", candidate, index)}
      />
    );
  }

  if (routeMode === "loop") return renderDetail();

  const chipClass =
    "rounded-full border border-[var(--color-border)] aria-pressed:border-[var(--color-accent)] aria-pressed:bg-[var(--color-accent-bg)] aria-pressed:shadow-[inset_0_0_0_1px_var(--color-accent)]";
  const arrow = (
    <span aria-hidden="true" className="flex-none text-[length:var(--font-size-xs)] text-[var(--color-muted)]">
      ›
    </span>
  );
  const endChip = (role: "origin" | "destination", title: string, name: string) => (
    <Button
      variant="ghost"
      size="bare"
      shape="pill"
      className={cn(chipClass, "relative overflow-hidden p-0.5")}
      aria-pressed={isShown({ role })}
      aria-label={`${title}: ${name}`}
      onClick={() => select({ role })}
    >
      <PointMark role={role} originLocated={originLocated} />
      <span
        data-chip-name
        className={cn(
          // 右の余白は名前が持つ（出さない間に測る幅へ入れる）。
          "pr-1.5 text-[length:var(--font-size-sm)] text-[var(--foreground)]",
          !namesShown && "invisible absolute top-0 left-0",
        )}
      >
        {name}
      </span>
    </Button>
  );

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex min-w-0 items-center gap-1">
        <div ref={stripRef} role="group" aria-label="地点の並び" className="flex min-w-0 flex-1 items-center gap-1">
          {endChip("origin", "出発地", originName)}
          {arrow}
          {/* 番号の丸は押す所（24px四方）を隙間なく並べ、両端の名前に幅を残す。 */}
          <span className="flex flex-none items-center">
            {waypoints.map((point, index) => (
              <Button
                key={index}
                variant="ghost"
                size="bare"
                shape="pill"
                className={cn(chipClass, "border-transparent p-px")}
                aria-pressed={isShown({ role: "waypoint", index })}
                aria-label={`経由地${index + 1}: ${foundAt(point)?.name ?? "地図で選んだ地点"}`}
                onClick={() => select({ role: "waypoint", index })}
              >
                <PointMark role="waypoint" label={String(index + 1)} originLocated={originLocated} />
              </Button>
            ))}
            <Button
              variant="ghost"
              size="bare"
              shape="pill"
              className={cn(
                chipClass,
                "ml-0.5 border-dashed px-1.5 py-0.5 text-[length:var(--font-size-sm)] text-[var(--color-accent-strong)]",
              )}
              aria-pressed={isShown({ role: "waypoint", index: null })}
              aria-label={waypointCount >= MAX_WAYPOINTS ? "経由地は上限まで置いてあります" : "経由地を足す"}
              disabled={waypointCount >= MAX_WAYPOINTS}
              onClick={() => select({ role: "waypoint", index: null })}
              usage="経由地を足します。地図をタップするか、住所・施設で探して置きます。"
            >
              ＋
            </Button>
          </span>
          {arrow}
          {endChip("destination", "目的地", destinationName)}
        </div>
        {/* 消すものが無い間も押せない状態で残す（置き場が動くと、並びの名前の出し分けが揺れる）。 */}
        <Button
          size="panelIcon"
          className="flex-none"
          aria-label="経由地と目的地を全部消す"
          disabled={waypointCount === 0 && destination === null}
          onClick={() => {
            clearPoints();
            setChosen(null);
          }}
          usage="置いた経由地と目的地を全部消します。出発地はそのままです。"
        >
          <ClearPointsIcon size={18} />
        </Button>
      </div>
      {renderDetail()}
    </div>
  );
}

"use client";

import { TabsContent } from "@/components/ui/Tabs/Tabs";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import type { Coordinates, PinRole, PlaceCandidate } from "@/types/route";
import { placedName } from "@/features/route/PlaceSearch/PlaceCandidates";
import type { GenerationConditionsState } from "@/features/route/useGenerationConditions";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { MIN_DISTANCE_KM } from "@/features/route/savedConditions";
import PointRow from "./PointRow";
import { fixedRouteCount, type RouteMode } from "./useRouteFormSubmit";
import { Button } from "@/components/ui/Button/Button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup/ToggleGroup";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

/** 「ルート設定」区分のタブ。タブ列と選択状態はpage.tsxが持ち（見出し行に置くため）、
 * ここは各タブの中身だけを描く。 */
export type SettingsTab = "generate" | "weights" | "exclusions" | "saved";

/** 「条件」タブが読む生成の条件（`features/route/useGenerationConditions.ts`の返り値をそのまま渡す）。距離・候補数は
 * 文字列のまま持つ——生成条件のdirty判定（`features/route/useRouteGeneration.ts`）に使うため。候補数は周回モードと、
 * 目的地モードで経由地が無い場合に意味を持つ（経由地を伴う目的地ルートはbackendが常に1件へ固定し無視する）。 */
type RouteFormConditions = Pick<
  GenerationConditionsState,
  | "distanceInput"
  | "setDistanceInput"
  | "maxRoutesInput"
  | "setMaxRoutesInput"
  | "routeMode"
  | "changeRouteMode"
  | "waypoints"
  | "clearWaypoints"
  | "destination"
  | "clearDestination"
  | "armedPinRole"
  | "armPinRole"
  | "foundAt"
>;

interface RouteFormProps {
  /** 生成の条件と、それを変える操作。 */
  conditions: RouteFormConditions;
  /** 出発地を地図で置き直してあるか（falseなら現在地のまま）。 */
  originManual: boolean;
  /** 出発地が実際の位置か（現在地を取れたか、地図で置いたか）。falseの間は地図のピンと同じく印を灰色にし、
   * 行の値も「現在地」と出さない（位置が仮の地点のままであることを、行と地図で示す）。 */
  originLocated: boolean;
  /** 出発地を現在地へ戻す（現在地の取得もこの操作が兼ねる）。 */
  onOriginReset: () => void;
  /** 出発地が、探して置いたときの位置のままなら、その候補（行に名前を出す）。 */
  originFound: PlaceCandidate | null;
  /** 地図でいま見ている所の真ん中。行で探す施設の候補は、ここから近い順に並ぶ。 */
  mapCenter: Coordinates;
  /** 行で探して選んだ候補を、その行の役割の地点として置く。 */
  onPlaceFound: (role: PinRole, candidate: PlaceCandidate) => void;
  /** 「重み」タブの中身。タブの列と「ルート生成」ボタンは見出しの行（page.tsx）、検証は`useRouteFormSubmit`が持つ。 */
  weightsPanel: React.ReactNode;
  /** 「除外」タブの中身。 */
  exclusionsPanel: React.ReactNode;
  /** 「保存」タブの中身（保存した条件の一覧と保存）。 */
  savedPanel: React.ReactNode;
}

const MAX_DISTANCE_KM = routeGenerateConfig.max_distance_km;
const DISTANCE_TOLERANCE_KM = routeGenerateConfig.default_distance_tolerance_km;
const MIN_ROUTES = routeGenerateConfig.min_routes;
const MAX_ROUTES = routeGenerateConfig.max_routes;
const MAX_WAYPOINTS = routeGenerateConfig.max_waypoints;

export default function RouteForm({
  conditions,
  originManual,
  originLocated,
  onOriginReset,
  originFound,
  mapCenter,
  onPlaceFound,
  weightsPanel,
  exclusionsPanel,
  savedPanel,
}: RouteFormProps) {
  const {
    distanceInput,
    setDistanceInput,
    maxRoutesInput,
    setMaxRoutesInput,
    routeMode,
    changeRouteMode,
    clearWaypoints,
    clearDestination,
    armedPinRole,
    armPinRole,
    foundAt,
  } = conditions;
  const waypointCount = conditions.waypoints.length;
  const destinationSet = conditions.destination !== null;
  const fixedCount = fixedRouteCount(routeMode, waypointCount);
  const maxRoutesRelevant = fixedCount === null;

  // 範囲の端ではボタンを押せなくするので、足した値は範囲を出ない。
  function stepMaxRoutes(delta: number) {
    setMaxRoutesInput(String(Number(maxRoutesInput) + delta));
  }

  // 出発地・経由地・目的地は同じ形の行で並べる（役割が同じ「地点を置く」操作のため）。
  // 武装は1つだけで、押している行以外は自動的に解除される（`features/route/useGenerationConditions.ts: armedPinRole`）。
  const rowProps = { onArm: armPinRole, originLocated, mapCenter, onPlaceFound };
  // 出発地はどちらのモードでも置ける（現在地が取れないときの案内が指す入口）。
  const originRow = (
    <PointRow
      role="origin"
      armed={armedPinRole === "origin"}
      {...rowProps}
      label="出発地"
      value={
        originManual
          ? originFound !== null
            ? placedName(originFound)
            : "地図で指定"
          : originLocated
            ? "現在地"
            : "現在地を取得できていません"
      }
      valueSet={originManual || originLocated}
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
    />
  );
  const destinationFound = foundAt("destination", conditions.destination);

  return (
    <div>
      {/* forceMount+data-stateでの表示切替（ルート結果のタブと同じ方式）。
          候補数等は`features/route/useGenerationConditions.ts`の制御stateのため非表示中も値は失われないが、
          重みタブ（RouteSettingsPanel）はドラッグ中の帯グラフ・チェックOFF前の
          重み記憶をローカルstateで持つため、タブ切替のたびにアンマウントすると失われる。 */}
      <TabsContent value="generate" forceMount className="data-[state=inactive]:hidden">
        {/* モードと候補数は同じ行に置く。候補数はどちらのモードでも効く共通の条件で、
            モードごとの入力（距離／地点）とは別の階層にある。 */}
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <ToggleGroup
            className="shrink-0"
            value={routeMode}
            onValueChange={(mode) => changeRouteMode(mode as RouteMode)}
            aria-label="ルート生成モード"
          >
            <ToggleGroupItem value="loop" usage="出発地から出て出発地へ戻る、指定した距離のルートを作ります。">
              周回
            </ToggleGroupItem>
            <ToggleGroupItem
              value="destination"
              usage="地図で置いた目的地へ向かうルートを作ります。経由地を置くと、そこを通ります。"
            >
              目的地
            </ToggleGroupItem>
          </ToggleGroup>
          {/* 経由地があるとbackendは決まった数へ固定する（route_request.py:
              applied_max_routes）。押せない状態で残す——消えると壊れて見えるうえ、
              複数候補へ広げる予定があるため置き場を動かさない。理由は隣の(i)の奥。 */}
          <div className="flex items-center gap-2 data-[disabled=true]:opacity-55" data-disabled={!maxRoutesRelevant}>
            <span className={cn(textVariants({ variant: "hint" }), "flex-shrink-0")}>候補数</span>
            {!maxRoutesRelevant && (
              <InfoPopover triggerAriaLabel="候補数を変えられない理由">
                経由地を置いている間は、その地点を通る経路を{fixedCount}本だけ引きます。候補数は経由地を
                消すと使えます。
              </InfoPopover>
            )}
            <div className="inline-flex items-center gap-2">
              <Button
                variant="stepper"
                size="sm"
                onClick={() => stepMaxRoutes(-1)}
                disabled={!maxRoutesRelevant || Number(maxRoutesInput) <= MIN_ROUTES}
                aria-label="候補数を減らす"
                usage="一度に作る候補の数を減らします。経由地を置いている間は変えられません。"
              >
                ‹
              </Button>
              <span className="min-w-[2.5em] text-center tabular-nums">{`${fixedCount ?? maxRoutesInput}件`}</span>
              <Button
                variant="stepper"
                size="sm"
                onClick={() => stepMaxRoutes(1)}
                disabled={!maxRoutesRelevant || Number(maxRoutesInput) >= MAX_ROUTES}
                aria-label="候補数を増やす"
                usage="一度に作る候補の数を増やします。経由地を置いている間は変えられません。"
              >
                ›
              </Button>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          {routeMode === "loop" ? (
            <>
              {originRow}
              <div className="flex items-center gap-2">
                <label htmlFor="route-form-distance" className={cn(textVariants({ variant: "hint" }), "flex-shrink-0")}>
                  距離
                </label>
                <input
                  id="route-form-distance"
                  type="range"
                  min={MIN_DISTANCE_KM}
                  max={MAX_DISTANCE_KM}
                  step={1}
                  value={distanceInput}
                  onChange={(e) => setDistanceInput(e.target.value)}
                  className="h-6 min-w-0 flex-1"
                  data-usage={`周回するルートの長さを決めます。作る候補は、この距離の±${DISTANCE_TOLERANCE_KM}kmに入るものだけです。`}
                />
                <span className="min-w-[3.5em] flex-shrink-0 text-right tabular-nums">{distanceInput}km</span>
                <span className={cn(textVariants({ variant: "hint" }), "flex-shrink-0 tabular-nums")}>
                  ±{DISTANCE_TOLERANCE_KM}km
                </span>
              </div>
            </>
          ) : (
            <div className="flex flex-col gap-1">
              {originRow}
              <PointRow
                role="waypoint"
                armed={armedPinRole === "waypoint"}
                {...rowProps}
                label="経由地"
                markLabel={waypointCount > 0 ? String(waypointCount) : undefined}
                value={waypointCount > 0 ? `${waypointCount}地点` : "なし"}
                valueSet={waypointCount > 0}
                armLabel="追加"
                extra={
                  waypointCount > 0 ? (
                    <Button
                      variant="ghost"
                      size="bare"
                      className="p-1 text-xs"
                      aria-label="経由地をクリア"
                      onClick={clearWaypoints}
                    >
                      ✕
                    </Button>
                  ) : undefined
                }
                armedHint={waypointCount > 0 ? `地図をタップ[${waypointCount}地点]` : "地図をタップ"}
                usage="押してから地図をタップするたびに、そこを通る経由地を足します。もう一度押すとやめます。"
                full={waypointCount >= MAX_WAYPOINTS}
              />
              <PointRow
                role="destination"
                armed={armedPinRole === "destination"}
                {...rowProps}
                label="目的地"
                value={
                  destinationSet ? (destinationFound !== null ? placedName(destinationFound) : "地図で指定") : "未設定"
                }
                valueSet={destinationSet}
                armLabel={destinationSet ? "置き直す" : "地図で選ぶ"}
                extra={
                  destinationSet ? (
                    <Button
                      variant="ghost"
                      size="bare"
                      className="p-1 text-xs"
                      aria-label="目的地をクリア"
                      onClick={clearDestination}
                    >
                      ✕
                    </Button>
                  ) : undefined
                }
                usage="押してから地図をタップすると、そこを目的地にします。もう一度押すとやめます。"
              />
            </div>
          )}
        </div>
      </TabsContent>

      <TabsContent value="weights" forceMount className="data-[state=inactive]:hidden">
        {weightsPanel}
      </TabsContent>

      <TabsContent value="exclusions" forceMount className="data-[state=inactive]:hidden">
        {exclusionsPanel}
      </TabsContent>

      <TabsContent value="saved" forceMount className="data-[state=inactive]:hidden">
        {savedPanel}
      </TabsContent>
    </div>
  );
}

"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import type { Coordinates, PinRole, PlaceCandidate } from "@/types/route";
import type { GenerationConditionsState } from "@/features/route/useGenerationConditions";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { MIN_DISTANCE_KM } from "@/features/route/savedConditions";
import SavedPlacesPanel from "@/features/route/SavedPlacesPanel/SavedPlacesPanel";
import type { SavedPlacesState } from "@/features/route/useSavedPlaces";
import RoutePoints from "./RoutePoints";
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
  | "removeWaypoint"
  | "destination"
  | "clearDestination"
  | "clearPoints"
  | "armedPinRole"
  | "waypointToReplace"
  | "armPinRole"
  | "foundAt"
>;

interface RouteFormProps {
  /** 生成の条件と、それを変える操作。 */
  conditions: RouteFormConditions;
  /** 出発地の位置（現在地か、地図で置いた地点）。 */
  origin: Coordinates;
  /** 出発地を地図で置き直してあるか（falseなら現在地のまま）。 */
  originManual: boolean;
  /** 出発地が実際の位置か（現在地を取れたか、地図で置いたか）。falseの間は地図のピンと同じく印を灰色にし、
   * 名前も「現在地」と出さない（位置が仮の地点のままであることを、パネルと地図で示す）。 */
  originLocated: boolean;
  /** 出発地を現在地へ戻す（現在地の取得もこの操作が兼ねる）。 */
  onOriginReset: () => void;
  /** 出発地が、探して置いたときの位置のままなら、その候補（名前を出す）。 */
  originFound: PlaceCandidate | null;
  /** 地図でいま見ている所の真ん中。探す施設の候補は、ここから近い順に並ぶ。 */
  mapCenter: Coordinates;
  /** 探して選んだ候補を、その役割の地点として置く（経由地は`waypointIndex`番目を置き直し、無ければ足す）。 */
  onPlaceFound: (role: PinRole, candidate: PlaceCandidate, waypointIndex: number | null) => void;
  /** 保存した地点（地点の詳しくで保存して打つ欄の候補に出し、「保存」タブの「地点」に並べる）。 */
  savedPlaces: SavedPlacesState;
  /** 「重み」タブの中身。タブの列と「ルート生成」ボタンは見出しの行（page.tsx）、検証は`useRouteFormSubmit`が持つ。 */
  weightsPanel: React.ReactNode;
  /** 「除外」タブの中身。 */
  exclusionsPanel: React.ReactNode;
  /** 「保存」タブの「設定」の中身（保存した条件の一覧と保存）。 */
  savedConditionsPanel: React.ReactNode;
}

const MAX_DISTANCE_KM = routeGenerateConfig.max_distance_km;
const DISTANCE_TOLERANCE_KM = routeGenerateConfig.default_distance_tolerance_km;
const MIN_ROUTES = routeGenerateConfig.min_routes;
const MAX_ROUTES = routeGenerateConfig.max_routes;

export default function RouteForm({
  conditions,
  origin,
  originManual,
  originLocated,
  onOriginReset,
  originFound,
  mapCenter,
  onPlaceFound,
  savedPlaces,
  weightsPanel,
  exclusionsPanel,
  savedConditionsPanel,
}: RouteFormProps) {
  const { distanceInput, setDistanceInput, maxRoutesInput, setMaxRoutesInput, routeMode, changeRouteMode } = conditions;
  const fixedCount = fixedRouteCount(routeMode, conditions.waypoints.length);
  const maxRoutesRelevant = fixedCount === null;

  // 範囲の端ではボタンを押せなくするので、足した値は範囲を出ない。
  function stepMaxRoutes(delta: number) {
    setMaxRoutesInput(String(Number(maxRoutesInput) + delta));
  }

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
          {/* 出発地はどちらのモードでも置ける（現在地が取れないときの案内が指す入口）。 */}
          <RoutePoints
            conditions={conditions}
            origin={origin}
            originManual={originManual}
            originLocated={originLocated}
            onOriginReset={onOriginReset}
            originFound={originFound}
            mapCenter={mapCenter}
            onPlaceFound={onPlaceFound}
            savedPlaces={savedPlaces}
          />
          {routeMode === "loop" && (
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
        {/* 保存するものは地点と設定の2つで、呼び出し方が違う（地点は打つ欄から1地点へ置き、設定は各タブの値を入れ替える）。 */}
        <Tabs defaultValue="places">
          <TabsList className="mb-2" aria-label="保存するもの">
            <TabsTrigger value="places" usage="名前を付けて保存した地点の一覧です。">
              地点
            </TabsTrigger>
            <TabsTrigger value="conditions" usage="いまの設定に名前を付けて保存し、保存した設定を呼び出します。">
              設定
            </TabsTrigger>
          </TabsList>
          <TabsContent value="places" forceMount className="data-[state=inactive]:hidden">
            <SavedPlacesPanel places={savedPlaces.places} onRemove={savedPlaces.remove} />
          </TabsContent>
          <TabsContent value="conditions" forceMount className="data-[state=inactive]:hidden">
            {savedConditionsPanel}
          </TabsContent>
        </Tabs>
      </TabsContent>
    </div>
  );
}

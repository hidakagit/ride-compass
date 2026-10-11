"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
import type { Coordinates, PinRole, PlaceCandidate } from "@/types/route";
import type { GenerationConditionsState } from "@/features/route/useGenerationConditions";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { MIN_DISTANCE_KM } from "@/features/route/savedConditions";
import SavedPlacesPanel from "@/features/route/SavedPlacesPanel/SavedPlacesPanel";
import type { SavedPlacesState } from "@/features/route/useSavedPlaces";
import RoutePoints from "./RoutePoints";
import { Button } from "@/components/ui/Button/Button";
import { DistanceTargetIcon } from "@/components/ui/icons/icons";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { textVariants } from "@/components/ui/Text/Text";
import { panelIconToggleClass, Toggle } from "@/components/ui/Toggle/Toggle";
import { cn } from "@/lib/cn";

/** 「ルート設定」区分のタブ。タブ列と選択状態はpage.tsxが持ち（見出し行に置くため）、
 * ここは各タブの中身だけを描く。 */
export type SettingsTab = "generate" | "weights" | "exclusions" | "saved";

/** 「条件」タブが読む生成の条件（`features/route/useGenerationConditions.ts`の返り値をそのまま渡す）。距離・候補数は
 * 文字列のまま持つ——生成条件のdirty判定（`features/route/useRouteGeneration.ts`）に使うため。 */
type RouteFormConditions = Pick<
  GenerationConditionsState,
  | "distanceInput"
  | "setDistanceInput"
  | "maxRoutesInput"
  | "setMaxRoutesInput"
  | "distanceTargeted"
  | "setDistanceTargeted"
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

// forceMount+data-stateでの表示切替（ルート結果のタブと同じ方式）。
// 候補数等は`features/route/useGenerationConditions.ts`の制御stateのため非表示中も値は失われないが、
// 重みタブ（RouteSettingsPanel）はドラッグ中の帯グラフ・チェックOFF前の
// 重み記憶をローカルstateで持つため、タブ切替のたびにアンマウントすると失われる。
function KeptTabContent({ value, children }: { value: string; children: React.ReactNode }) {
  return (
    <TabsContent value={value} forceMount className="data-[state=inactive]:hidden">
      {children}
    </TabsContent>
  );
}

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
  const { distanceTargeted, setDistanceTargeted, distanceInput, setDistanceInput, maxRoutesInput, setMaxRoutesInput } =
    conditions;
  const distanceToggleName = distanceTargeted ? "全長の目標をやめる" : "全長の目標を決める";

  // 範囲の端ではボタンを押せなくするので、足した値は範囲を出ない。
  function stepMaxRoutes(delta: number) {
    setMaxRoutesInput(String(Number(maxRoutesInput) + delta));
  }

  return (
    <div>
      <KeptTabContent value="generate">
        <div className="mb-2 flex items-center justify-end gap-2">
          <span className={cn(textVariants({ variant: "hint" }), "flex-shrink-0")}>候補数</span>
          <div className="inline-flex items-center gap-2">
            <Button
              variant="stepper"
              size="sm"
              onClick={() => stepMaxRoutes(-1)}
              disabled={Number(maxRoutesInput) <= MIN_ROUTES}
              aria-label="候補数を減らす"
              usage="一度に作る候補の数を減らします。"
            >
              ‹
            </Button>
            <span className="min-w-[2.5em] text-center tabular-nums">{`${maxRoutesInput}件`}</span>
            <Button
              variant="stepper"
              size="sm"
              onClick={() => stepMaxRoutes(1)}
              disabled={Number(maxRoutesInput) >= MAX_ROUTES}
              aria-label="候補数を増やす"
              usage="一度に作る候補の数を増やします。"
            >
              ›
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-2">
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
          {/* 外している間もスライダーと値は出したまま薄くする（入れ直すと前の値に戻ることが見え、行の高さも変わらない）。 */}
          <div className="flex items-center gap-2">
            <Toggle
              variant="plain"
              className={cn(panelIconToggleClass, "flex-none")}
              pressed={distanceTargeted}
              aria-label={distanceToggleName}
              title={distanceToggleName}
              onClick={() => setDistanceTargeted(!distanceTargeted)}
              usage="押している間は、ルート全体の長さを目標に合わせます。"
            >
              <DistanceTargetIcon />
            </Toggle>
            <input
              aria-label="全長の目標"
              type="range"
              min={MIN_DISTANCE_KM}
              max={MAX_DISTANCE_KM}
              step={1}
              value={distanceInput}
              disabled={!distanceTargeted}
              onChange={(e) => setDistanceInput(e.target.value)}
              className="h-6 min-w-0 flex-1 disabled:opacity-40"
              data-usage="ルート全体の長さの目標を決めます。"
            />
            <span
              className={cn("min-w-[3.5em] flex-shrink-0 text-right tabular-nums", !distanceTargeted && "opacity-40")}
            >
              {distanceInput}km
            </span>
            <InfoPopover triggerAriaLabel="全長の目標の説明" triggerClassName="flex-none">
              {`ルート全体の長さの目標です。作る候補は、この長さの±${DISTANCE_TOLERANCE_KM}kmに入るものだけです。外すと長さを決めず、目的地（無ければ出発地）へ良い道で向かいます。`}
            </InfoPopover>
          </div>
        </div>
      </KeptTabContent>

      <KeptTabContent value="weights">{weightsPanel}</KeptTabContent>

      <KeptTabContent value="exclusions">{exclusionsPanel}</KeptTabContent>

      <KeptTabContent value="saved">
        {/* 保存するものは地点と設定の2つで、呼び出し方が違う（地点は打つ欄から1地点へ置き、設定は各タブの値を入れ替える）。 */}
        <Tabs defaultValue="places">
          <TabsList className="mb-2" aria-label="保存するもの">
            <TabsTrigger value="places" usage="名前を付けて保存した地点の一覧です。">
              地点
            </TabsTrigger>
            <TabsTrigger
              value="conditions"
              usage="名前を付けて保存した設定の一覧です。呼び出すと、各タブの値を入れ替えます。"
            >
              設定
            </TabsTrigger>
          </TabsList>
          <KeptTabContent value="places">
            <SavedPlacesPanel places={savedPlaces.places} onRemove={savedPlaces.remove} />
          </KeptTabContent>
          <KeptTabContent value="conditions">{savedConditionsPanel}</KeptTabContent>
        </Tabs>
      </KeptTabContent>
    </div>
  );
}

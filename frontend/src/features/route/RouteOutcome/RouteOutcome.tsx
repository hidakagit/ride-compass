"use client";

import { Fragment } from "react";

import AxisContributionBar from "@/components/AxisContributionBar/AxisContributionBar";
import ErrorText from "@/features/route/ErrorText/ErrorText";
import { Button } from "@/components/ui/Button/Button";
import { GuideText } from "@/components/ui/GuideText/GuideText";
import { ClockIcon, DownloadIcon, RouteSpliceIcon } from "@/components/ui/icons/icons";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
import { textVariants } from "@/components/ui/Text/Text";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { useResearchEnabled } from "@/hooks/useResearchMode";
import { formatMaterialValue, MATERIAL_CATALOG, materialCatalogName } from "@/lib/axisMaterialsCatalog";
import { cn } from "@/lib/cn";
import { formatJstHourMinute } from "@/lib/time";
import ComparisonPanel from "@/features/route/ComparisonPanel/ComparisonPanel";
import DifficultyProfile from "@/features/route/DifficultyProfile/DifficultyProfile";
import AxisDetail from "@/features/route/RouteAxisProfile/AxisDetail";
import RouteAxisProfile from "@/features/route/RouteAxisProfile/RouteAxisProfile";
import RouteSplicePanel from "@/features/route/RouteSplicePanel/RouteSplicePanel";
import SegmentWind from "@/features/route/SegmentWind/SegmentWind";
import { baselineDistanceKm, loadBarHeightRatio } from "@/features/route/difficultyLoadBar";
import { formatDurationShort } from "@/features/route/formatDuration";
import { downloadGpx, MAX_GPX_TRACK_POINTS } from "@/features/route/gpxExport";
import EditDifference from "@/features/route/EditDifference/EditDifference";
import {
  extraDurationLabel,
  fastestDurationSeconds,
  fastestRouteId,
  routeListSections,
} from "@/features/route/routeTabLabel";
import type { useRouteGeneration } from "@/features/route/useRouteGeneration";
import { COMPARISON_TAB, type RouteResults } from "@/features/route/useRouteResults";
import type { SpliceSessionView } from "@/features/route/useSpliceSession";
import type { RouteCandidate, RoutePreferenceWeights } from "@/types/route";

const CANDIDATE_TAB_USAGE =
  "この候補を地図と内訳に出します。距離のあとに、最も早い候補は所要時間、ほかは最速より余計にかかる時間、右端に総合難易度が並びます。";

function formatSegmentArrivalTime(iso: string | null): string {
  if (!iso) return "不明";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "不明";
  return formatJstHourMinute(date);
}

type RouteGeneration = ReturnType<typeof useRouteGeneration>;

interface RouteOutcomeProps {
  results: RouteResults;
  /** 生成の進み方・案内・条件のずれ・実験スロット。 */
  generation: Pick<
    RouteGeneration,
    | "running"
    | "progressLabel"
    | "lastMessage"
    | "failure"
    | "conditionsDirty"
    | "weightsNotApplied"
    | "destinationCorrected"
    | "experimentSlots"
    | "generatedInput"
  >;
  splice: Pick<SpliceSessionView, "canStart" | "start" | "panel">;
  /** 軸を「未使用」と分ける重み（`useRoutePlanner.ts: routeWeights`）。 */
  routeWeights: RoutePreferenceWeights;
}

/**
 * 「ルート結果」の中身（デスクトップの区分・モバイルのシートの両方）: 生成前・生成中・失敗の案内、候補の一覧（縦のタブ）と
 * 選んだ候補の中身・地図で押した区間の詳細、研究モードの比較、編集中は区間の乗り換えの編集面。
 */
export default function RouteOutcome({ results, generation, splice, routeWeights }: RouteOutcomeProps) {
  const axisCatalog = useAxisCatalog();
  const researchEnabled = useResearchEnabled();
  const { routes, selectedRouteId, comparisonTabActive, selectedRouteSegment } = results;

  // 「ルート結果」に候補が無いときの中身（生成前・生成中・失敗）。候補0件で生成前の案内へ戻ると、押したのに何も
  // 起きていないように見える。
  function renderRouteOutcomeEmptyState() {
    if (generation.running) {
      return <p className={textVariants({ variant: "hint" })}>{generation.progressLabel ?? "生成中..."}</p>;
    }
    if (generation.lastMessage) {
      return <ErrorText>{generation.lastMessage}</ErrorText>;
    }
    return (
      <p className={textVariants({ variant: "hint" })}>
        <GuideText text="「ルート設定」の「ルート生成」を押すと候補がここに並びます" />
      </p>
    );
  }

  // 候補1本への操作（合成・GPX出力）。その候補のタブの中身の先頭に置く。
  function renderCandidateActions(route: RouteCandidate) {
    return (
      <div className="flex items-center gap-1.5">
        {/* 合成（区間の乗り換え）の入口。乗り換えできない生成（周回・候補1件）では出さない。 */}
        {splice.canStart && (
          <Button
            size="panelIcon"
            onClick={() => {
              splice.start(route.id);
              // 区間の詳細の置き場は編集面に置き換わるため、選択を外す（地図に印だけが残らない）。
              results.selectSegment(null);
            }}
            aria-label="ルートを合成"
            usage="この候補の一部の区間を、ほかの候補が通る道へ乗り換えて新しいルートを作ります。押すと、乗り換えられる道が地図に破線で出ます。"
          >
            <RouteSpliceIcon size={18} />
          </Button>
        )}
        <Button
          size="panelIcon"
          onClick={() => downloadGpx(route)}
          aria-label="GPX出力"
          usage={`この候補をGPXファイルで書き出します。サイクルコンピューターやほかの地図アプリに読み込めます。点の数は${MAX_GPX_TRACK_POINTS}点に収まるように間引きます。`}
        >
          <DownloadIcon size={18} />
        </Button>
      </div>
    );
  }

  // 編集で作ったルートの中身の先頭に、元との違いを出す。
  function renderEditDifference(route: RouteCandidate, nameOf: (routeId: string) => string) {
    const edit = results.edits.find((item) => item.route.id === route.id);
    const origin = edit && routes.find((candidate) => candidate.id === edit.originId);
    if (!edit || !origin) return null;
    return (
      <EditDifference
        originName={nameOf(origin.id)}
        origin={origin}
        edited={route}
        onShowOrigin={() => results.selectTab(origin.id)}
      />
    );
  }

  // 「ルート結果」の中身（デスクトップの区分・モバイルのシートの両方）。候補がある間に「生成」が通らなかったら、
  // 前の候補を残したまま先頭で知らせる（候補だけが並ぶと、作り直せたように見える）。
  function renderRouteOutcome() {
    if (routes.length === 0) return renderRouteOutcomeEmptyState();
    return (
      <>
        {generation.failure && <ErrorText>作り直せませんでした。{generation.failure}</ErrorText>}
        {renderRouteOutcomeSectionBody()}
      </>
    );
  }

  // 候補ごとのタブ＋「比較」タブの1列で、タブの切り替えが候補の切り替えを兼ねる。
  function renderRouteOutcomeSectionBody() {
    // 編集中は同じ場所が編集面になる（「ルート編集」という別の置き場を持たない）。元は1本に固定で、相手を
    // 選び直しても変わらない。
    if (splice.panel) return <RouteSplicePanel {...splice.panel} />;

    const showComparisonTab = researchEnabled;
    // 所要時間だけで選んだ1本を生成が必ず含めるのは、経由地の無い目的地ルートだけ。
    const input = generation.generatedInput;
    const sections = routeListSections(
      results.generated,
      results.edits,
      input !== null && input.destination !== null && input.waypoints.length === 0,
    );
    const nameOf = (routeId: string) =>
      sections.flatMap((section) => section.entries).find((entry) => entry.route.id === routeId)?.name ?? "";
    const outerTabValue = comparisonTabActive ? COMPARISON_TAB : (selectedRouteId ?? routes[0].id);
    const fastestSeconds = fastestDurationSeconds(routes);
    const fastestRouteIdInList = fastestRouteId(routes);
    // 難易度の帯の高さ1.0とする距離（面積が負荷になる）。一覧の行と候補の中身で同じ基準を使う。
    const loadBarBaselineKm = baselineDistanceKm(routes);
    // 道のりのグラフの横軸の右端。候補どうしで同じ物差しにし、面積（負荷）を見比べられるようにする。
    const longestDistanceKm = Math.max(0, ...routes.map((route) => route.distance_km));

    return (
      <>
        {/* 作り直しの失敗を出している間は、それが前の条件の候補であることも伝えているので重ねない。 */}
        {generation.conditionsDirty && !generation.failure && (
          <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--color-warning-strong)]">
            生成条件が変更されています
          </p>
        )}
        {generation.weightsNotApplied && (
          <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--color-warning-strong)]">
            重み配分を反映できず、既定の配分で作りました。
          </p>
        )}
        {generation.destinationCorrected && (
          <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--color-warning-strong)]">
            指定した地点は自転車で行けない場所だったため、近くのアクセス可能な地点へ補正しました。
          </p>
        )}
        <Tabs
          className="flex min-h-0 flex-row items-stretch gap-2 max-mobile:flex-auto"
          // 候補は横並びでは幅に収まらず溢れて消えるため、1行1候補の縦並びにし、行へ距離と難易度を並べる。
          orientation="vertical"
          value={outerTabValue}
          onValueChange={results.selectTab}
        >
          {/* 狭幅では下部シートの高さいっぱいまで伸ばし、はみ出す候補は一覧の中だけを縦スクロールさせる——一覧に固定の
              高さ上限を置くと、シートに余白があっても伸びずに触れない余白が残る。 */}
          <div className="flex w-48 flex-none items-stretch border-r border-[var(--color-border)]">
            <TabsList variant="side" className="max-mobile:min-h-0 max-mobile:overflow-y-auto" aria-label="ルート結果">
              {sections.map((section) => (
                <Fragment key={section.title ?? ""}>
                  {section.title !== null && (
                    <p className={cn(textVariants({ variant: "note" }), "m-0 px-2 pt-2 pb-0.5 font-medium first:pt-0")}>
                      {section.title}
                    </p>
                  )}
                  {section.entries.map(({ route, name, nameShown }) => (
                    <TabsTrigger key={route.id} value={route.id} usage={CANDIDATE_TAB_USAGE}>
                      {/* 値を省略で切らず、幅に収まらないときだけ所要時間を次の行へ送る（切られた値は画面のどこにも出ない）。 */}
                      <span className="flex min-w-0 flex-wrap items-center gap-x-1">
                        {/* 見分けるための名前（番号・編集N）と距離。 */}
                        <span>
                          {nameShown && `${name} `}
                          {route.distance_km.toFixed(1)}km
                        </span>
                        {/* 最速の候補はその所要時間を印付きで、他の候補はそこから何分余計にかかるか（見比べる場所に置く）。 */}
                        {route.id === fastestRouteIdInList && fastestSeconds !== null ? (
                          <span
                            className="inline-flex items-center gap-0.5 font-normal text-[var(--color-muted-strong)]"
                            title="最速"
                          >
                            <span role="img" aria-label="最速" className="inline-flex">
                              <ClockIcon size={11} />
                            </span>
                            {formatDurationShort(fastestSeconds)}
                          </span>
                        ) : (
                          extraDurationLabel(route, fastestSeconds) && (
                            <span className="font-normal text-[var(--color-muted-strong)]">
                              {extraDurationLabel(route, fastestSeconds)}
                            </span>
                          )
                        )}
                      </span>
                      {/* 総合難易度を数値と長さで。算出できなかった候補は「—」だけ（0と欠損を同じ見た目にしない）。 */}
                      <span className="flex flex-shrink-0 items-center justify-end gap-1">
                        <span
                          className="h-[calc(0.35rem*var(--load-bar-height-ratio,1))] w-6 flex-shrink-0 overflow-hidden rounded-[2px] bg-[var(--color-border)]"
                          style={
                            {
                              "--load-bar-height-ratio": String(
                                loadBarHeightRatio(route.distance_km, loadBarBaselineKm),
                              ),
                            } as React.CSSProperties & { "--load-bar-height-ratio"?: string }
                          }
                        >
                          {route.overall_difficulty !== null && (
                            <span
                              className="block h-full rounded-l-[2px] bg-[var(--color-accent)] opacity-70"
                              style={{ width: `${route.overall_difficulty.average}%` }}
                            />
                          )}
                        </span>
                        <span className="font-normal text-[var(--color-muted-strong)] tabular-nums">
                          {route.overall_difficulty === null ? "—" : Math.round(route.overall_difficulty.average)}
                        </span>
                      </span>
                    </TabsTrigger>
                  ))}
                </Fragment>
              ))}
              {showComparisonTab && <TabsTrigger value={COMPARISON_TAB}>比較</TabsTrigger>}
            </TabsList>
          </div>
          <div className="min-w-0 flex-auto">
            {routes.map((route) => (
              <TabsContent key={route.id} className="flex flex-col gap-2 data-[state=inactive]:hidden" value={route.id}>
                {renderCandidateActions(route)}
                {renderEditDifference(route, nameOf)}
                {/* 道のりに沿った難易度。区間を選んでいる間も残す（動かして地点を選ぶ操作の置き場のため）。 */}
                {route.segments.length > 0 && (
                  <DifficultyProfile
                    segments={route.segments}
                    overallDifficulty={route.overall_difficulty?.average ?? null}
                    axisOrder={axisCatalog.axes.map((axis) => axis.axisId)}
                    axisColors={axisCatalog.axisColors}
                    scaleKm={longestDistanceKm}
                    selected={selectedRouteSegment}
                    onSelect={results.selectSegment}
                  />
                )}
                {/* 押した区間がある間は、その区間の地点・到達予想・内訳を出す（区間は選んでいる候補にしか描かれない）。 */}
                {selectedRouteSegment ? (
                  <div className="flex flex-col gap-2">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="inline-flex items-baseline gap-2 text-[length:var(--font-size-md)] font-medium">
                        <span className="whitespace-nowrap">
                          {selectedRouteSegment.segment.cumulative_distance_km.toFixed(1)} km地点
                        </span>
                        <span className={cn(textVariants({ variant: "hint" }), "break-keep")}>
                          到達予想 {formatSegmentArrivalTime(selectedRouteSegment.segment.estimated_arrival_time)}
                        </span>
                      </span>
                      <Button
                        variant="ghost"
                        size="bare"
                        className="px-1 text-[1.1rem]"
                        aria-label="区間の選択を解除"
                        onClick={() => results.selectSegment(null)}
                      >
                        ×
                      </Button>
                    </div>
                    <SegmentWind wind={selectedRouteSegment.segment.wind} />
                    <AxisContributionBar
                      axes={axisCatalog.axes}
                      contributions={selectedRouteSegment.segment.axis_contributions}
                      axisColors={axisCatalog.axisColors}
                      renderDetail={(axis) => (
                        <AxisDetail
                          axis={axis}
                          difficulty={selectedRouteSegment.segment.axis_difficulties[axis.axisId]}
                        />
                      )}
                    />
                    {researchEnabled && Object.keys(selectedRouteSegment.segment.material_values).length > 0 && (
                      <ul className={cn(textVariants({ variant: "hint" }), "m-0 flex list-none flex-col gap-0.5 p-0")}>
                        {/* 名前を引けない材料は出さない——材料idは内部名。 */}
                        {Object.entries(selectedRouteSegment.segment.material_values).flatMap(([materialId, value]) => {
                          const name = materialCatalogName(materialId, MATERIAL_CATALOG);
                          return name === undefined
                            ? []
                            : [
                                <li key={materialId}>
                                  {name}: {formatMaterialValue(materialId, value, MATERIAL_CATALOG)}
                                </li>,
                              ];
                        })}
                      </ul>
                    )}
                  </div>
                ) : (
                  <RouteAxisProfile
                    axes={axisCatalog.axes}
                    weights={routeWeights}
                    axisDifficulties={route.axis_difficulties}
                    axisContributions={route.axis_contributions}
                    axisRawValues={route.axis_raw_values}
                    materialValues={route.material_values}
                    materialCategoryShares={route.material_category_shares}
                    distanceKm={route.distance_km}
                    overallDifficulty={route.overall_difficulty}
                    estimatedDurationSeconds={route.estimated_duration_seconds}
                    windUnavailable={route.wind_unavailable}
                    missingTravelDataShare={route.missing_travel_data_share}
                    axisColors={axisCatalog.axisColors}
                  />
                )}
              </TabsContent>
            ))}
            {showComparisonTab && (
              // 開いていない間も描いておき、隠すだけにする。
              <TabsContent
                className="flex flex-col gap-2 data-[state=inactive]:hidden"
                value={COMPARISON_TAB}
                forceMount
              >
                {/* 比較の軸は各スロットを作ったときの重みで選ぶ（いまの重みで絞ると、重みを0にした軸の差が比較から消える）。 */}
                <ComparisonPanel
                  slots={generation.experimentSlots}
                  axisLabels={axisCatalog.axisLabels}
                  axes={axisCatalog.axes.filter((axis) =>
                    generation.experimentSlots.some((slot) => (slot.conditions.route_preference[axis.axisId] ?? 0) > 0),
                  )}
                  materials={MATERIAL_CATALOG}
                />
              </TabsContent>
            )}
          </div>
        </Tabs>
      </>
    );
  }

  return renderRouteOutcome();
}

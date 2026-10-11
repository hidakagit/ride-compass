"use client";

import { Fragment, useEffect, useMemo, useRef } from "react";

import AxisContributionBar, { hasContribution } from "@/components/AxisContributionBar/AxisContributionBar";
import { Button } from "@/components/ui/Button/Button";
import { GuideText } from "@/components/ui/GuideText/GuideText";
import { DownloadIcon, FastestRouteIcon, RouteSpliceIcon } from "@/components/ui/icons/icons";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
import { textVariants } from "@/components/ui/Text/Text";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { cn } from "@/lib/cn";
import { formatDifficulty } from "@/lib/mapDisplay/valueScale";
import { formatJstHourMinute } from "@/lib/time";
import DifficultyProfile from "@/features/route/DifficultyProfile/DifficultyProfile";
import AxisDetail from "@/components/AxisContributionBar/AxisDetail";
import RouteAxisProfile from "@/features/route/RouteAxisProfile/RouteAxisProfile";
import RouteSplicePanel from "@/features/route/RouteSplicePanel/RouteSplicePanel";
import SegmentWind from "@/features/route/SegmentWind/SegmentWind";
import { formatDurationShort } from "@/features/route/formatDuration";
import { downloadGpx, MAX_GPX_TRACK_POINTS } from "@/features/route/gpxExport";
import EditDifference from "@/features/route/EditDifference/EditDifference";
import GenerationNotice from "@/features/route/GenerationNotice/GenerationNotice";
import WarningText from "@/features/route/WarningText/WarningText";
import {
  durationBaseline,
  durationDifferenceLabel,
  routeListEntries,
  type RouteListGroup,
} from "@/features/route/routeTabLabel";
import type { useRouteGeneration } from "@/features/route/useRouteGeneration";
import type { RouteResults } from "@/features/route/useRouteResults";
import type { SpliceSessionView } from "@/features/route/useSpliceSession";
import type { RouteCandidate, RoutePreferenceWeights } from "@/types/route";

const CANDIDATE_TAB_USAGE =
  "この候補を地図と内訳に出します。名前の稲妻の印は最も早く着く最速ルート、合成の印は区間を乗り換えて作った合成ルートで、番号だけのものは生成した候補です。列は距離（km）・時間（最速ルート［無ければ最も早い候補］は所要時間、ほかはそれとの差で、速ければ−）・総合難易度です。";

/** 名前の列で群を見分ける印と、その意味（指を置いたときの吹き出しと読み上げの名前）。生成した候補は印を持たない。 */
const GROUP_MARKS: Partial<Record<RouteListGroup, { Icon: typeof FastestRouteIcon; meaning: string }>> = {
  fastest: { Icon: FastestRouteIcon, meaning: "最速ルート" },
  spliced: { Icon: RouteSpliceIcon, meaning: "合成ルート" },
};

function formatSegmentArrivalTime(iso: string | null): string {
  if (!iso) return "不明";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "不明";
  return formatJstHourMinute(date);
}

type RouteGeneration = ReturnType<typeof useRouteGeneration>;

interface RouteOutcomeProps {
  results: RouteResults;
  /** 生成の進み方・案内・条件のずれ。 */
  generation: Pick<
    RouteGeneration,
    | "running"
    | "progressLabel"
    | "outcome"
    | "failure"
    | "conditionsDirty"
    | "weightsNotApplied"
    | "destinationCorrected"
  >;
  splice: Pick<SpliceSessionView, "canStart" | "start" | "panel">;
  /** 軸を「未使用」と分ける重み（`useRoutePlanner.ts: routeWeights`）。 */
  routeWeights: RoutePreferenceWeights;
}

/**
 * 「ルート結果」の中身（デスクトップの区分・モバイルのシートの両方）: 生成前・生成中・失敗の案内、候補の一覧（縦のタブ）と
 * 選んだ候補の中身・地図で押した区間の詳細、編集中は区間の乗り換えの編集面。
 */
export default function RouteOutcome({ results, generation, splice, routeWeights }: RouteOutcomeProps) {
  const axisCatalog = useAxisCatalog();
  // 道のりのグラフが下から積む軸の並び。同じ参照を渡し、描き直しのたびにグラフの形を組み直させない。
  const axisOrder = useMemo(() => axisCatalog.axes.map((axis) => axis.axisId), [axisCatalog.axes]);
  const { routes, selectedRouteId, selectedRouteSegment, reusedRouteId } = results;
  // 乗り換えで作った経路と同じ道だったので選んだ行。一覧の見える範囲の外にあっても、選んだことが見えるように出す。
  const reusedRowRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (reusedRouteId !== null) reusedRowRef.current?.scrollIntoView({ block: "nearest" });
  }, [reusedRouteId]);

  // 「ルート結果」に候補が無いときの中身（生成前・生成中・候補0件・失敗）。候補0件で生成前の案内へ戻ると、押したのに何も
  // 起きていないように見える。
  function renderRouteOutcomeEmptyState() {
    const { outcome } = generation;
    if (generation.running) {
      return <p className={textVariants({ variant: "hint" })}>{generation.progressLabel ?? "生成中..."}</p>;
    }
    if (outcome) return <GenerationNotice notice={outcome} />;
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
        {generation.failure && (
          <GenerationNotice notice={{ kind: "failed", message: `作り直せませんでした。${generation.failure}` }} />
        )}
        {renderRouteOutcomeSectionBody()}
      </>
    );
  }

  // 候補ごとのタブの1列で、タブの切り替えが候補の切り替えを兼ねる。
  function renderRouteOutcomeSectionBody() {
    const entries = routeListEntries(results.generated, results.edits);
    const nameOf = (routeId: string) => entries.find((entry) => entry.route.id === routeId)?.name ?? "";
    // 編集中は同じ場所が編集面になる（「ルート編集」という別の置き場を持たない）。元は1本に固定で、相手を
    // 選び直しても変わらない。
    if (splice.panel) {
      const { sameRouteId, ...panel } = splice.panel;
      return <RouteSplicePanel {...panel} sameRouteName={sameRouteId === null ? null : nameOf(sameRouteId)} />;
    }

    const baseline = durationBaseline(routes);
    // 道のりのグラフの横軸の右端。候補どうしで同じ物差しにし、面積（負荷）を見比べられるようにする。
    const longestDistanceKm = Math.max(0, ...routes.map((route) => route.distance_km));

    return (
      <>
        {/* 作り直しの失敗を出している間は、それが前の条件の候補であることも伝えているので重ねない。 */}
        {generation.conditionsDirty && !generation.failure && <WarningText>生成条件が変更されています</WarningText>}
        {generation.weightsNotApplied && <WarningText>重み配分を反映できず、既定の配分で作りました。</WarningText>}
        {generation.destinationCorrected && (
          <WarningText>
            指定した地点は自転車で行けない場所だったため、近くのアクセス可能な地点へ補正しました。
          </WarningText>
        )}
        {reusedRouteId !== null && (
          <p className={cn(textVariants({ variant: "hint" }), "m-0")}>
            作った組み合わせは「{nameOf(reusedRouteId)}」と同じ道なので、「{nameOf(reusedRouteId)}」を選びました
          </p>
        )}
        <Tabs
          className="flex min-h-0 flex-row items-stretch gap-2 max-mobile:flex-auto"
          // 候補は横並びでは幅に収まらず溢れて消えるため、1行1候補の縦並びにし、行へ距離と難易度を並べる。
          orientation="vertical"
          value={selectedRouteId ?? routes[0].id}
          onValueChange={results.selectTab}
        >
          {/* 狭幅では下部シートの高さいっぱいまで伸ばし、はみ出す候補は一覧の中だけを縦スクロールさせる——一覧に固定の
              高さ上限を置くと、シートに余白があっても伸びずに触れない余白が残る。
              列（名前・距離・時間・難易度）は一覧全体の格子にそろえ、一覧の幅は列が折り返さずに収まる最小にする。 */}
          <div className="flex flex-none items-stretch border-r border-[var(--color-border)]">
            <TabsList
              variant="side"
              className="grid grid-cols-[repeat(4,auto)] content-start gap-x-2 max-mobile:min-h-0 max-mobile:overflow-y-auto"
              aria-label="ルート結果"
            >
              {/* 列の見出し。行の読み上げの名前は単位と項目を自分で持つので、見出しは読み上げない。 */}
              <div
                aria-hidden
                className={cn(
                  textVariants({ variant: "note" }),
                  "col-span-full grid grid-cols-subgrid border-l-3 border-transparent px-2 pb-0.5 text-right",
                )}
              >
                <span />
                <span>km</span>
                <span>時間</span>
                <span>難易度</span>
              </div>
              {entries.map(({ route, group, label }, index) => {
                const mark = GROUP_MARKS[group];
                return (
                  <Fragment key={route.id}>
                    {index > 0 && group !== entries[index - 1].group && (
                      <hr className="col-span-full m-0 border-0 border-t border-[var(--color-border)]" />
                    )}
                    {/* セルの間の空白は格子には出ず、読み上げの名前でだけ項目を区切る。 */}
                    <TabsTrigger
                      ref={route.id === reusedRouteId ? reusedRowRef : undefined}
                      value={route.id}
                      usage={CANDIDATE_TAB_USAGE}
                      className="col-span-full grid grid-cols-subgrid"
                    >
                      <span className="inline-flex items-center gap-0.5">
                        {mark && (
                          <span role="img" aria-label={mark.meaning} title={mark.meaning} className="inline-flex">
                            <mark.Icon size={12} />
                          </span>
                        )}
                        {label}
                      </span>{" "}
                      <span className="text-right tabular-nums">
                        {route.distance_km.toFixed(1)}
                        <span className="sr-only">km</span>
                      </span>{" "}
                      {/* 基準線の候補はその所要時間、他の候補はそれとの差（見比べる場所に置く）。 */}
                      <span className="text-right font-normal text-[var(--color-muted-strong)] tabular-nums">
                        {route.id === baseline?.id
                          ? formatDurationShort(baseline.seconds)
                          : durationDifferenceLabel(route, baseline?.seconds ?? null)}
                      </span>{" "}
                      {/* 算出できなかった候補は「—」（0と欠損を同じ見た目にしない）。 */}
                      <span className="text-right font-normal text-[var(--color-muted-strong)] tabular-nums">
                        <span className="sr-only">難易度</span>
                        {route.overall_difficulty === null ? "—" : formatDifficulty(route.overall_difficulty.average)}
                      </span>
                    </TabsTrigger>
                  </Fragment>
                );
              })}
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
                    axisOrder={axisOrder}
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
                    {/* 内訳の帯は寄与が無いと何も描かないので、総合難易度を常に出し、全部0なら0であることを文で言う
                        （何も出ないと、壊れたのと見分けがつかない）。算出できなかった区間は「—」。 */}
                    <span className="inline-flex items-baseline gap-0.5">
                      <span className={textVariants({ variant: "hint" })}>総合難易度</span>
                      <span className="font-semibold">
                        {selectedRouteSegment.segment.difficulty === null
                          ? "—"
                          : formatDifficulty(selectedRouteSegment.segment.difficulty)}
                      </span>
                      <span className={textVariants({ variant: "hint" })}>/100</span>
                    </span>
                    {selectedRouteSegment.segment.difficulty !== null &&
                      !Object.keys(selectedRouteSegment.segment.axis_contributions).some((axisId) =>
                        hasContribution(selectedRouteSegment.segment.axis_contributions, axisId),
                      ) && <p className={cn(textVariants({ variant: "hint" }), "m-0")}>どの評価軸も0（易しい）</p>}
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
          </div>
        </Tabs>
      </>
    );
  }

  return renderRouteOutcome();
}

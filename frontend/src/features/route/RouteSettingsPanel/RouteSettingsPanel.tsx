"use client";

import { useEffect, useRef, useState } from "react";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { axisIconFor } from "@/components/ui/icons/axisIconPalette";
import { syncRoutePreferenceKeys } from "@/features/route/routePreferenceSync";
import { WEIGHT_STEP, clampBoundaryDrag, totalWeight } from "@/features/route/routeWeightShare";
import { retryAxisCatalogFetch, useAxisCatalog } from "@/hooks/useAxisCatalog";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights } from "@/types/route";
import { Button } from "@/components/ui/Button/Button";
import { Toggle } from "@/components/ui/Toggle/Toggle";
import { cn } from "@/lib/cn";
import { legendChipBodyClass, legendChipClass, legendIconClass } from "@/components/ui/AxisLegend/axisLegend";
import { calloutVariants } from "@/components/ui/Callout/Callout";

// 帯の区間へ文字を入れられる最小の取り分（%）。狭い区間はアイコン＋%→%だけ→何も出さない、の順に落とす
// （どの軸の%もチップでは必ず読める）。
const SEGMENT_ICON_MIN_PCT = 10;
const SEGMENT_VALUE_MIN_PCT = 6;

interface RouteSettingsPanelProps {
  routePreference: RoutePreferenceWeights;
  onRoutePreferenceChange: (next: RoutePreferenceWeights) => void;
  /** 重みを上書きするか。値を変えると自動でONになる（切り替えの操作はこのパネルに出さない）。 */
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
}

/** 「ルート設定」の「重み」タブ。配分の帯（境界のドラッグで配分し直す）と、軸のチップ（有効な軸を先頭に%付きで並べ、
 * 押すと有効/無効、(i)で説明）。軸は分類で分けず、公開軸を1本の並びで出す。 */
export default function RouteSettingsPanel({
  routePreference,
  onRoutePreferenceChange,
  overrideEnabled,
  onOverrideEnabledChange,
}: RouteSettingsPanelProps) {
  const catalog = useAxisCatalog();
  const handlePreferenceChange = (next: RoutePreferenceWeights) => {
    if (!overrideEnabled) onOverrideEnabledChange(true);
    onRoutePreferenceChange(next);
  };

  // `const Icon = axisIconFor(...); <Icon/>`を本体の直下に書くとreact-hooks/static-componentsが誤検知するので、関数を通す。
  function AxisIcon({ axis, size = 14 }: { axis: PreferenceAxisDef; size?: number }) {
    const Icon = axisIconFor(axis.iconId);
    return <Icon size={size} />;
  }

  // 重みのキーを公開軸と揃える（backendは全軸のキーを求め、どちらにずれても生成が422になる）。キーの足し引きだけなので
  // 上書きのフラグは動かさない。取得が決まるまでは揃えない（0件のまま突き合わせると、保存済みの重みを全部消す）。
  useEffect(() => {
    if (!catalog.loaded) return;
    const synced = syncRoutePreferenceKeys(routePreference, catalog.defaultWeights);
    if (synced) onRoutePreferenceChange(synced);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.defaultWeights, catalog.loaded]);

  // 無効にした軸の重みを覚えておき、有効に戻したときに戻す（送る値の側は0になるので、ここでしか持てない）。
  const [lastWeights, setLastWeights] = useState<Record<string, number>>(() => ({
    ...catalog.defaultWeights,
  }));
  // 既定の重みが届いたら、手で変えていない軸だけを新しい既定へ追従させる（しないと、届く前の値へ戻ってしまう）。
  const previousDefaultWeightsRef = useRef(catalog.defaultWeights);
  useEffect(() => {
    const previousDefaults = previousDefaultWeightsRef.current;
    previousDefaultWeightsRef.current = catalog.defaultWeights;
    if (previousDefaults === catalog.defaultWeights) return;
    setLastWeights((prev) => {
      const next = { ...prev };
      for (const [axisId, defaultWeight] of Object.entries(catalog.defaultWeights)) {
        if (!(axisId in prev) || prev[axisId] === previousDefaults[axisId]) {
          next[axisId] = defaultWeight;
        }
      }
      return next;
    });
  }, [catalog.defaultWeights]);

  function handleToggle(axisId: string, checked: boolean) {
    const restored = checked ? lastWeights[axisId] || catalog.defaultWeights[axisId] || 0.1 : 0;
    handlePreferenceChange({ ...routePreference, [axisId]: restored });
  }

  // 隣り合う2軸を1回の更新へまとめる（1軸ずつ2回呼ぶと、2回目が1回目を反映しない値から組むので1回目が消える）。
  function handlePairWeightChange(axisIdA: string, valueA: number, axisIdB: string, valueB: number) {
    setLastWeights((prev) => ({ ...prev, [axisIdA]: valueA, [axisIdB]: valueB }));
    handlePreferenceChange({ ...routePreference, [axisIdA]: valueA, [axisIdB]: valueB });
  }

  const total = totalWeight(routePreference);
  // 有効な軸（重み>0）にだけ使うため、合計は必ず正。
  const sharePct = (weight: number) => (weight / total) * 100;

  // 有効な軸を先に並べる（スクロールせずに今の%を読める）。
  const axesWithWeight = catalog.axes.map((axis) => ({
    axis,
    weight: routePreference[axis.axisId] ?? 0,
  }));
  const enabledAxes = axesWithWeight.filter(({ weight }) => weight > 0);
  const orderedAxes = [...enabledAxes, ...axesWithWeight.filter(({ weight }) => weight <= 0)];
  // 境界ごとの累積の%。
  const cumulativePcts = enabledAxes.reduce<number[]>(
    (acc, { weight }) => [...acc, (acc.at(-1) ?? 0) + sharePct(weight)],
    [],
  );

  // 帯の境界を動かすと、両隣の2軸の間でだけ重みが移る。つまみは細く、ドラッグ中は外へ出るのが常なので、windowで
  // 受ける（pointer captureは環境によって効かない）。
  const stackBarRef = useRef<HTMLDivElement>(null);
  function startBoundaryDrag(
    e: React.PointerEvent<HTMLDivElement>,
    axisIdA: string,
    startWeightA: number,
    axisIdB: string,
    startWeightB: number,
  ) {
    const bar = stackBarRef.current;
    if (!bar) return;
    const barWidthPx = bar.getBoundingClientRect().width;
    if (barWidthPx <= 0) return;
    const startClientX = e.clientX;
    const pixelsPerUnit = barWidthPx / total;
    const handleWindowPointerMove = (moveEvent: PointerEvent) => {
      const rawDelta = (moveEvent.clientX - startClientX) / pixelsPerUnit;
      const { weightA, weightB } = clampBoundaryDrag(startWeightA, startWeightB, rawDelta);
      handlePairWeightChange(axisIdA, weightA, axisIdB, weightB);
    };
    const handleWindowPointerUp = () => {
      window.removeEventListener("pointermove", handleWindowPointerMove);
      window.removeEventListener("pointerup", handleWindowPointerUp);
      window.removeEventListener("pointercancel", handleWindowPointerUp);
    };
    window.addEventListener("pointermove", handleWindowPointerMove);
    window.addEventListener("pointerup", handleWindowPointerUp);
    window.addEventListener("pointercancel", handleWindowPointerUp);
  }

  function handleBoundaryKeyDown(
    e: React.KeyboardEvent<HTMLDivElement>,
    axisIdA: string,
    weightA: number,
    axisIdB: string,
    weightB: number,
  ) {
    let rawDelta = 0;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") rawDelta = -WEIGHT_STEP;
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") rawDelta = WEIGHT_STEP;
    else return;
    e.preventDefault();
    const next = clampBoundaryDrag(weightA, weightB, rawDelta);
    if (next.weightA === weightA && next.weightB === weightB) return;
    handlePairWeightChange(axisIdA, next.weightA, axisIdB, next.weightB);
  }

  function renderLegendChip(axis: PreferenceAxisDef, weight: number) {
    const checked = weight > 0;
    const color = catalog.axisColors[axis.axisId];
    const label = axis.chipLabel ?? axis.label;
    return (
      <span key={axis.axisId} className={legendChipClass} data-checked={checked}>
        <Toggle
          variant="plain"
          className={cn(legendChipBodyClass, "cursor-pointer")}
          pressed={checked}
          aria-label={checked ? `${axis.label}を無効にする` : `${axis.label}を有効にする`}
          onClick={() => handleToggle(axis.axisId, !checked)}
        >
          <span aria-hidden="true" className={legendIconClass} style={{ color }}>
            <AxisIcon axis={axis} />
          </span>
          <span>{label}</span>
          {checked && (
            <span className="text-[length:var(--font-size-sm)] font-semibold tabular-nums">
              {Math.round(sharePct(weight))}%
            </span>
          )}
        </Toggle>
        <InfoPopover
          triggerClassName={"w-7 border-l border-[var(--color-border-muted)] max-mobile:w-6"}
          triggerAriaLabel={`${axis.label}の説明`}
        >
          {axis.description}
        </InfoPopover>
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* 軸カタログが取れないと重みは送られず（backendの既定で探す）、同じ応答が運ぶタイルの世代も無いので地図の
          道路・POI・事故も出ない。何が起きるかと再試行をここで見せる（再試行の入口はここだけ）。 */}
      {catalog.failed && (
        <p
          className={cn(
            calloutVariants({ tone: "warning" }),
            "flex flex-wrap items-center gap-2 text-[length:var(--font-size-xs)]",
          )}
          role="status"
        >
          <span>
            {/* JSXの改行は半角スペースになるので、文字列として繋ぐ。 */}
            {"軸一覧を取得できませんでした。地図の道路・POI・事故は表示できず、このまま生成すると" +
              "重み配分は反映されずサーバー既定の配分で探索します。"}
          </span>
          <Button variant="warning" size="xs" onClick={retryAxisCatalogFetch}>
            再試行
          </Button>
        </p>
      )}
      <div className="flex flex-col">
        <div className="relative" ref={stackBarRef}>
          <div className="flex h-7.5 gap-px overflow-hidden rounded-sm bg-[var(--color-surface-2)]">
            {enabledAxes.map(({ axis, weight }) => {
              const pct = sharePct(weight);
              return (
                <div
                  key={axis.axisId}
                  className="flex h-full min-w-0 flex-col items-center justify-center gap-px overflow-hidden"
                  style={{ width: `${pct}%`, background: catalog.axisColors[axis.axisId] }}
                  title={`${axis.label} ${Math.round(pct)}%`}
                >
                  {pct >= SEGMENT_ICON_MIN_PCT && (
                    <span aria-hidden="true" className="inline-flex text-[rgba(15,23,42,0.85)]">
                      <AxisIcon axis={axis} size={13} />
                    </span>
                  )}
                  {pct >= SEGMENT_VALUE_MIN_PCT && (
                    <span
                      aria-hidden="true"
                      className="text-[0.625rem] leading-none font-bold text-[rgba(15,23,42,0.85)] tabular-nums"
                    >
                      {Math.round(pct)}
                      {pct >= SEGMENT_ICON_MIN_PCT ? "%" : ""}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          {enabledAxes.slice(0, -1).map(({ axis: left, weight: leftWeight }, i) => {
            const cumulativePct = cumulativePcts[i];
            const right = enabledAxes[i + 1];
            return (
              <div
                key={`boundary-${left.axisId}-${right.axis.axisId}`}
                className="absolute -top-1.5 -bottom-1.5 flex w-4 -translate-x-1/2 cursor-col-resize touch-none items-center justify-center after:h-3.5 after:w-0.5 after:rounded-[1px] after:bg-[var(--color-surface)] after:shadow-[0_0_0_1px_var(--color-border-strong)] after:content-[''] hover:after:bg-[var(--color-accent)] hover:after:shadow-[0_0_0_1px_var(--color-accent)] focus-visible:outline-none focus-visible:after:bg-[var(--color-accent)] focus-visible:after:shadow-[0_0_0_1px_var(--color-accent)]"
                style={{ left: `${cumulativePct}%` }}
                role="slider"
                aria-label={`${left.label}と${right.axis.label}の配分`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(cumulativePct)}
                tabIndex={0}
                onPointerDown={(e) => startBoundaryDrag(e, left.axisId, leftWeight, right.axis.axisId, right.weight)}
                onKeyDown={(e) => handleBoundaryKeyDown(e, left.axisId, leftWeight, right.axis.axisId, right.weight)}
              />
            );
          })}
        </div>
      </div>

      <div className="flex max-h-26 flex-wrap gap-2 overflow-y-auto">
        {orderedAxes.map(({ axis, weight }) => renderLegendChip(axis, weight))}
      </div>
    </div>
  );
}

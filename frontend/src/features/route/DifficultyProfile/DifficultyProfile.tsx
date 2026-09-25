"use client";

import { useState, type KeyboardEvent, type PointerEvent } from "react";

import palette from "@/types/generated/palette.json";
import type { RouteSegmentDetail, SelectedRouteSegment } from "@/types/route";

import { columnAtKm, pointAlongSegment, profileBoxes, profileColumns, type ProfileBox } from "./difficultyProfile";

/** 描画の座標。横は距離を`VIEW_WIDTH`へ、縦は難易度0〜100をそのまま使い、枠いっぱいへ伸ばす。 */
const VIEW_WIDTH = 1000;
const VIEW_HEIGHT = 100;
/** 矢印キー1回で動く距離（全長に対する割合）。 */
const KEY_STEP_RATIO = 0.01;

interface DifficultyProfileProps {
  segments: readonly RouteSegmentDetail[];
  /** ルートの総合難易度。値の無い区間をこの高さで描く（負荷の計算と同じ扱い）。 */
  overallDifficulty: number | null;
  /** 下から積む軸の並びと色。 */
  axisOrder: readonly string[];
  axisColors: Readonly<Record<string, string>>;
  /** 横軸の右端の距離。一覧の中で最も長い候補の距離にすると、候補どうしで面積（負荷）を見比べられる。 */
  scaleKm: number;
  selected: SelectedRouteSegment | null;
  onSelect: (selection: SelectedRouteSegment) => void;
}

function boxesPath(boxes: readonly ProfileBox[], xOf: (km: number) => number): string {
  return boxes
    .map(
      (box) =>
        `M${xOf(box.startKm)} ${VIEW_HEIGHT - box.top}H${xOf(box.endKm)}V${VIEW_HEIGHT - box.bottom}H${xOf(box.startKm)}Z`,
    )
    .join("");
}

/** 道のりに沿った難易度。横が距離、縦が区間ごとの難易度で、塗った面積がルートの負荷になる。押したまま動かすと、
 * その距離の地点を選ぶ（地図に印が出て、下にその区間の詳細が出る）。 */
export default function DifficultyProfile({
  segments,
  overallDifficulty,
  axisOrder,
  axisColors,
  scaleKm,
  selected,
  onSelect,
}: DifficultyProfileProps) {
  const [scrubKm, setScrubKm] = useState<number | null>(null);
  const columns = profileColumns(segments);
  const routeKm = columns.length === 0 ? 0 : columns[columns.length - 1].endKm;
  const widthKm = Math.max(scaleKm, routeKm);
  if (routeKm <= 0 || widthKm <= 0) return null;

  const xOf = (km: number) => Math.round((km / widthKm) * VIEW_WIDTH * 100) / 100;
  const { byAxis, missing } = profileBoxes(columns, axisOrder, overallDifficulty);
  const selectedColumn = selected === null ? undefined : columns.find((column) => column.segment === selected.segment);
  // 自分で動かした地点がいま選ばれている区間の中にあるときだけ線を引く（地図で区間を押したときは区間の帯だけ）。
  const cursorKm =
    selectedColumn !== undefined &&
    scrubKm !== null &&
    scrubKm >= selectedColumn.startKm &&
    scrubKm <= selectedColumn.endKm
      ? scrubKm
      : null;

  function selectAt(km: number) {
    const clamped = Math.min(routeKm, Math.max(0, km));
    const hit = columnAtKm(columns, clamped);
    if (hit === null) return;
    const [longitude, latitude] = pointAlongSegment(hit.column.segment, hit.fraction);
    setScrubKm(clamped);
    onSelect({ segment: hit.column.segment, latitude, longitude });
  }

  function kmAtPointer(event: PointerEvent<SVGSVGElement>): number {
    const rect = event.currentTarget.getBoundingClientRect();
    return rect.width > 0 ? ((event.clientX - rect.left) / rect.width) * widthKm : 0;
  }

  function handleKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    const current = cursorKm ?? selectedColumn?.startKm ?? 0;
    const step = routeKm * KEY_STEP_RATIO;
    const next =
      event.key === "ArrowRight"
        ? current + step
        : event.key === "ArrowLeft"
          ? current - step
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? routeKm
              : null;
    if (next === null) return;
    event.preventDefault();
    selectAt(next);
  }

  return (
    <div className="flex flex-col gap-0.5">
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        preserveAspectRatio="none"
        // 押したまま横へ動かす操作をシートのスクロール・スワイプへ渡さない。
        className="h-14 w-full cursor-crosshair touch-none rounded-sm bg-[var(--color-surface-2)] outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]"
        role="slider"
        tabIndex={0}
        aria-label="道のりに沿った難易度（動かすと、その地点を地図に出す）"
        aria-valuemin={0}
        aria-valuemax={Math.round(routeKm * 10) / 10}
        aria-valuenow={Math.round((cursorKm ?? selectedColumn?.startKm ?? 0) * 10) / 10}
        aria-valuetext={`${(cursorKm ?? selectedColumn?.startKm ?? 0).toFixed(1)} km地点`}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture?.(event.pointerId);
          selectAt(kmAtPointer(event));
        }}
        onPointerMove={(event) => {
          if (event.buttons === 0) return;
          selectAt(kmAtPointer(event));
        }}
        onKeyDown={handleKeyDown}
      >
        {selectedColumn !== undefined && (
          <rect
            x={xOf(selectedColumn.startKm)}
            y={0}
            width={Math.max(xOf(selectedColumn.endKm) - xOf(selectedColumn.startKm), 2)}
            height={VIEW_HEIGHT}
            fill={palette.semantic.inspected}
            opacity={0.25}
          />
        )}
        {missing.length > 0 && <path d={boxesPath(missing, xOf)} fill={palette.semantic.no_data} opacity={0.6} />}
        {axisOrder.map((axisId) => {
          const boxes = byAxis.get(axisId) ?? [];
          if (boxes.length === 0) return null;
          return <path key={axisId} d={boxesPath(boxes, xOf)} fill={axisColors[axisId] ?? palette.semantic.no_data} />;
        })}
        {cursorKm !== null && (
          <line
            x1={xOf(cursorKm)}
            x2={xOf(cursorKm)}
            y1={0}
            y2={VIEW_HEIGHT}
            stroke={palette.semantic.inspected}
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
      <div className="flex justify-between text-[length:var(--font-size-xs)] text-[var(--color-muted)] tabular-nums">
        <span>0</span>
        <span>{widthKm.toFixed(1)}km</span>
      </div>
    </div>
  );
}

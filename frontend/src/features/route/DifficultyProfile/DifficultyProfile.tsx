"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import palette from "@/types/generated/palette.json";
import type { RouteSegmentDetail, SelectedRouteSegment } from "@/types/route";

import { columnAtKm, pointAlongSegment, profileBoxes, profileColumns, type ProfileBox } from "./profileGeometry";

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

/** 距離を描画の横座標へ。 */
function xAt(km: number, widthKm: number): number {
  return Math.round((km / widthKm) * VIEW_WIDTH * 100) / 100;
}

function boxesPath(boxes: readonly ProfileBox[], xOf: (km: number) => number): string {
  return boxes
    .map(
      (box) =>
        `M${xOf(box.startKm)} ${VIEW_HEIGHT - box.top}H${xOf(box.endKm)}V${VIEW_HEIGHT - box.bottom}H${xOf(box.startKm)}Z`,
    )
    .join("");
}

/** 道のりに沿った難易度。横が距離、縦が区間ごとの難易度で、塗った面積がルートの負荷になる。1本の指（マウス）で
 * なぞるか押して離すと、その距離の地点を選ぶ（地図に印が出て、下にその区間の詳細が出る）。**押しただけでは選ばず、
 * 途中で2本目の指が触れた操作は選択にしない**——グラフの上で始めたピンチ（拡大しようとした操作）で区間が選ばれ、
 * 表示が区間の詳細へ切り替わらないようにする。 */
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
  // グラフに触れている指（ポインター）と、いまの操作に2本目が加わったか。
  const gesture = useRef<{ pointers: Set<number>; multi: boolean }>({ pointers: new Set(), multi: false });
  // 画面のどこかに触れている指。2本目はグラフの外に触れることがあり、グラフのポインターだけでは数えられない
  // （タッチイベントの指の数は、グラフのpointermoveより後に届くので間に合わない）。
  const screenPointers = useRef<Set<number>>(new Set());
  useEffect(() => {
    const pointers = screenPointers.current;
    const down = (event: globalThis.PointerEvent) => {
      pointers.add(event.pointerId);
      if (pointers.size > 1 && gesture.current.pointers.size > 0) gesture.current.multi = true;
    };
    const up = (event: globalThis.PointerEvent) => pointers.delete(event.pointerId);
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", up, true);
    return () => {
      window.removeEventListener("pointerdown", down, true);
      window.removeEventListener("pointerup", up, true);
      window.removeEventListener("pointercancel", up, true);
    };
  }, []);
  const columns = useMemo(() => profileColumns(segments), [segments]);
  const routeKm = columns.length === 0 ? 0 : columns[columns.length - 1].endKm;
  const widthKm = Math.max(scaleKm, routeKm);
  // 塗る形はルートと横軸が変わったときだけ組む（なぞる間に動くのは、カーソルの線と選んだ区間の帯だけ）。
  const paths = useMemo(() => {
    if (widthKm <= 0) return null;
    const xOf = (km: number) => xAt(km, widthKm);
    const { byAxis, missing } = profileBoxes(columns, axisOrder, overallDifficulty);
    return {
      missing: missing.length > 0 ? boxesPath(missing, xOf) : null,
      byAxis: axisOrder.flatMap((axisId) => {
        const boxes = byAxis.get(axisId) ?? [];
        return boxes.length === 0 ? [] : [{ axisId, d: boxesPath(boxes, xOf) }];
      }),
    };
  }, [columns, axisOrder, overallDifficulty, widthKm]);
  if (routeKm <= 0 || paths === null) return null;

  const xOf = (km: number) => xAt(km, widthKm);
  const selectedColumn = selected === null ? undefined : columns.find((column) => column.segment === selected.segment);
  // 自分で動かした地点がいま選ばれている区間の中にあるときだけ線を引く（地図で区間を押したときは区間の帯だけ）。
  const cursorKm =
    selectedColumn !== undefined &&
    scrubKm !== null &&
    scrubKm >= selectedColumn.startKm &&
    scrubKm <= selectedColumn.endKm
      ? scrubKm
      : null;
  const positionKm = cursorKm ?? selectedColumn?.startKm ?? 0;

  function selectAt(km: number) {
    // 横軸が候補より長いとき、候補の終わりより右は終点として選び、線も終点に引く。
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
    const step = routeKm * KEY_STEP_RATIO;
    const next =
      event.key === "ArrowRight"
        ? positionKm + step
        : event.key === "ArrowLeft"
          ? positionKm - step
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? routeKm
              : null;
    if (next === null) return;
    event.preventDefault();
    selectAt(next);
  }

  function releasePointer(pointerId: number) {
    gesture.current.pointers.delete(pointerId);
    if (gesture.current.pointers.size === 0) gesture.current.multi = false;
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
        data-usage="横が道のり、縦がその区間の難易度で、塗った面積がルートの負荷です。なぞるか押して離すと、その地点を地図に印で出し、下にその区間の詳細を出します。"
        aria-valuemin={0}
        aria-valuemax={Math.round(routeKm * 10) / 10}
        aria-valuenow={Math.round(positionKm * 10) / 10}
        aria-valuetext={`${positionKm.toFixed(1)} km地点`}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture?.(event.pointerId);
          gesture.current.pointers.add(event.pointerId);
          // 画面全体の指は窓の捕捉の段で先に数えてあるので、グラフの上の指もそこに含まれる。
          if (screenPointers.current.size > 1) gesture.current.multi = true;
        }}
        onPointerMove={(event) => {
          if (event.buttons === 0 || gesture.current.multi || !gesture.current.pointers.has(event.pointerId)) return;
          selectAt(kmAtPointer(event));
        }}
        onPointerUp={(event) => {
          if (!gesture.current.multi && gesture.current.pointers.has(event.pointerId)) selectAt(kmAtPointer(event));
          releasePointer(event.pointerId);
        }}
        onPointerCancel={(event) => releasePointer(event.pointerId)}
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
        {paths.missing !== null && <path d={paths.missing} fill={palette.semantic.no_data} opacity={0.6} />}
        {paths.byAxis.map(({ axisId, d }) => (
          <path key={axisId} d={d} fill={axisColors[axisId] ?? palette.semantic.no_data} />
        ))}
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

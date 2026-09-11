"use client";

// 折れ点をドラッグ・矢印キーで調整できる曲線エディタ。数値入力行（正確な値の入力・行の
// 追加削除）はAxisComposer側に残り、この曲線はその可視化＋補助的な操作手段として上に
// 添える（両者は同じdraft.breakpoints stateを指すため常に同期する）。
//
// 背景には実データの分布（生値のヒストグラムと分位）を薄く重ねる。折れ点だけを見ても
// 「その形が実際の道路のどこに効いているか」は分からず、値が集中する帯の外側で曲線を
// 動かしても結果は変わらない。重ね方の計算はcurveDistributionOverlay.ts（DOM非依存の
// 純関数）が行い、このファイルは描画のみ。

import { useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";

import { niceStep, snapToStep } from "./breakpointTools";
import {
  maxBarShare,
  offRangeShare,
  quantileMarkers,
  visibleBars,
  OFF_RANGE_NOTICE_THRESHOLD,
} from "./curveDistributionOverlay";
import type { ValueDistribution } from "./scoreDistribution";
import styles from "./AxisStudio.module.css";

/** きりのいい目盛り位置の一覧（min〜maxの範囲内、niceStep刻み）。 */
function niceTicks(min: number, max: number): number[] {
  const step = niceStep(max - min || 1);
  const start = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 1e-6; v += step) {
    ticks.push(Math.round(v * 1000) / 1000);
  }
  return ticks;
}

/** 折れ点(breakpoints)をドラッグ・矢印キーで調整できる曲線エディタ。既存の数値入力行
 * （正確な値の入力・行の追加削除）はそのまま残し、この曲線はその可視化＋補助的な操作手段
 * として上に添える（両者は同じdraft.breakpoints stateを指すため常に同期する）。
 * `referenceRange`（材料の参考点の値域）を渡すと横軸をその範囲に固定し、ドラッグ中に
 * 見た目のスケールが動かないようにする（材料の参考点が無い場合は現在のbreakpointsの
 * 値から自動スケールする）。 */
export function BreakpointCurveEditor({
  breakpoints,
  onChangePoint,
  referenceRange,
  distribution,
}: {
  breakpoints: [number, number][];
  onChangePoint: (index: number, pos: 0 | 1, value: number) => void;
  referenceRange?: { min: number; max: number };
  /** 折れ点を通す前の生値の分布。背景へ薄く重ねる。未取得・取得不可ならnull。 */
  distribution?: ValueDistribution | null;
}) {
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);
  const width = 400;
  const height = 160;
  const padding = 28;
  const xs = breakpoints.map((bp) => bp[0]);
  const ys = breakpoints.map((bp) => bp[1]);
  // referenceRangeがあれば10%の余白を持たせて横軸を固定し、無ければ現在のbreakpoints
  // から自動スケールする（従来どおり）。
  const xMin = referenceRange ? referenceRange.min - (referenceRange.max - referenceRange.min) * 0.1 : Math.min(...xs);
  const xMax = referenceRange ? referenceRange.max + (referenceRange.max - referenceRange.min) * 0.1 : Math.max(...xs);
  const yMin = Math.min(0, ...ys);
  const yMax = Math.max(100, ...ys);
  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;
  const xSnapStep = niceStep(xSpan);

  function toScreen(bp: [number, number]): [number, number] {
    const sx = padding + ((bp[0] - xMin) / xSpan) * (width - padding * 2);
    const sy = height - padding - ((bp[1] - yMin) / ySpan) * (height - padding * 2);
    return [sx, sy];
  }

  function fromScreen(sx: number, sy: number): [number, number] {
    const x = xMin + ((sx - padding) / (width - padding * 2)) * xSpan;
    const y = yMin + ((height - padding - sy) / (height - padding * 2)) * ySpan;
    return [snapToStep(x, xSnapStep), Math.round(y)];
  }

  const bars = visibleBars(distribution ?? null, xMin, xMax);
  const barScale = maxBarShare(bars);
  const markers = quantileMarkers(distribution ?? null, xMin, xMax);
  const offRange = offRangeShare(distribution ?? null, xMin, xMax);

  const points = breakpoints.map(toScreen);
  const polyline = points.map(([x, y]) => `${x},${y}`).join(" ");
  const xTicks = niceTicks(xMin, xMax);
  const yTicks = [25, 50, 75];

  function handlePointerMove(e: ReactPointerEvent<SVGCircleElement>, index: number) {
    if (e.buttons !== 1) return;
    const svg = e.currentTarget.ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const sx = ((e.clientX - rect.left) / rect.width) * width;
    const sy = ((e.clientY - rect.top) / rect.height) * height;
    const [x, y] = fromScreen(sx, sy);
    onChangePoint(index, 0, x);
    onChangePoint(index, 1, y);
  }

  // 矢印キーでの微調整（左右=入力値をxSnapStep刻み、上下=スコアを1刻み、Shift併用で
  // その10倍）。ドラッグ操作の代替手段として、キーボード操作・スクリーンリーダー
  // 利用者にも折れ点を動かす手段を確保する。
  function handleKeyDown(e: ReactKeyboardEvent<SVGCircleElement>, index: number) {
    const bigStep = e.shiftKey ? 10 : 1;
    if (e.key === "ArrowRight") {
      e.preventDefault();
      onChangePoint(index, 0, breakpoints[index][0] + xSnapStep * bigStep);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      onChangePoint(index, 0, breakpoints[index][0] - xSnapStep * bigStep);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      onChangePoint(index, 1, breakpoints[index][1] + bigStep);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      onChangePoint(index, 1, breakpoints[index][1] - bigStep);
    }
  }

  const dragging = draggingIndex != null ? breakpoints[draggingIndex] : null;
  const draggingScreen = draggingIndex != null ? points[draggingIndex] : null;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={styles.curveEditor}
      role="img"
      aria-label="折れ点の曲線プレビュー（背景は実データの分布。ドラッグまたは矢印キーで調整可能）"
    >
      {/* 実データの分布。棒は曲線・格子線より先に描いて最背面へ置く（前面に出ると
          折れ点のドラッグ対象が見えにくくなる）。高さは最大の階級を基準に正規化した
          相対値で、縦軸（得点）とは無関係。 */}
      {bars.map((bar) => {
        const [x0] = toScreen([bar.from, 0]);
        const [x1] = toScreen([bar.to, 0]);
        const h = (bar.share / barScale) * (height - padding * 2);
        return (
          <rect
            key={`bar-${bar.from}`}
            x={x0}
            y={height - padding - h}
            width={Math.max(x1 - x0, 0.5)}
            height={h}
            className={styles.curveDistributionBar}
          />
        );
      })}
      {markers.map((marker) => {
        const [sx] = toScreen([marker.value, 0]);
        return (
          <g key={`q-${marker.label}`}>
            <line x1={sx} y1={padding} x2={sx} y2={height - padding} className={styles.curveQuantileLine} />
            <text x={sx} y={padding - 3} className={styles.curveQuantileLabel} textAnchor="middle">
              {marker.label}
            </text>
          </g>
        );
      })}
      {yTicks.map((y) => {
        const [, sy] = toScreen([xMin, y]);
        return <line key={`y-${y}`} x1={padding} y1={sy} x2={width - padding} y2={sy} className={styles.curveGridline} />;
      })}
      {xTicks.map((x) => {
        const [sx] = toScreen([x, yMin]);
        return (
          <g key={`x-${x}`}>
            <line x1={sx} y1={padding} x2={sx} y2={height - padding} className={styles.curveGridline} />
            <text x={sx} y={height - padding + 12} className={styles.curveTickLabel} textAnchor="middle">
              {x}
            </text>
          </g>
        );
      })}
      <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} className={styles.curveAxis} />
      <line x1={padding} y1={padding} x2={padding} y2={height - padding} className={styles.curveAxis} />
      <polyline points={polyline} className={styles.curveLine} />
      {points.map(([x, y], i) => (
        <circle
          key={i}
          cx={x}
          cy={y}
          r={7}
          tabIndex={0}
          role="slider"
          aria-label={`折れ点${i + 1}（入力値${breakpoints[i][0]}、スコア${breakpoints[i][1]}）`}
          aria-valuenow={breakpoints[i][1]}
          className={styles.curvePoint}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            setDraggingIndex(i);
          }}
          onPointerMove={(e) => handlePointerMove(e, i)}
          onPointerUp={() => setDraggingIndex(null)}
          onKeyDown={(e) => handleKeyDown(e, i)}
        />
      ))}
      {/* 表示範囲の外にある延長。黙って切ると「分布は全部見えている」と読めてしまい、
          折れ点が実データの範囲と合っていないこと自体が画面から消える。 */}
      {offRange.below >= OFF_RANGE_NOTICE_THRESHOLD && (
        <text x={padding} y={padding - 3} className={styles.curveOffRangeLabel} textAnchor="start">
          ←{(offRange.below * 100).toFixed(0)}%
        </text>
      )}
      {offRange.above >= OFF_RANGE_NOTICE_THRESHOLD && (
        <text x={width - padding} y={padding - 3} className={styles.curveOffRangeLabel} textAnchor="end">
          {(offRange.above * 100).toFixed(0)}%→
        </text>
      )}
      {dragging && draggingScreen && (
        <text x={draggingScreen[0]} y={draggingScreen[1] - 12} className={styles.curveDragLabel} textAnchor="middle">
          {dragging[0]} → {dragging[1]}
        </text>
      )}
    </svg>
  );
}

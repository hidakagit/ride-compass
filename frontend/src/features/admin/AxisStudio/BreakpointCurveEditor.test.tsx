/**
 * `BreakpointCurveEditor.tsx`——折れ点を矢印キーとドラッグで動かす口、横軸の決め方（参考点の範囲に固定するか、
 * 折れ点から決めるか）、背景へ重ねる分布（棒・分位線・範囲外の割合）。
 *
 * 動かした結果は `onChangePoint` で親へ渡すだけで、折れ点そのものは親が持つ。
 *
 * ここで見ないもの:
 * - 分布の按分・範囲外の割合の計算 → `curveDistributionOverlay.test.ts`（期待値はそこの関数から引く）
 * - 刻みの選び方 → `breakpointTools.test.ts`（期待値は `niceStep` から引く）
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BreakpointCurveEditor } from "./BreakpointCurveEditor";
import { niceStep } from "./breakpointTools";
import { OFF_RANGE_NOTICE_THRESHOLD } from "./curveDistributionOverlay";
import type { ValueDistribution } from "./scoreDistribution";

const POINTS: [number, number][] = [
  [0, 0],
  [10, 100],
];

function distribution(overrides: Partial<ValueDistribution> = {}): ValueDistribution {
  return { sample_ways: 1, total_km: 1, quantiles: {}, bins: [], zero_share: 0, ...overrides };
}

function renderEditor(props: Partial<Parameters<typeof BreakpointCurveEditor>[0]> = {}) {
  const onChangePoint = vi.fn();
  const view = render(<BreakpointCurveEditor breakpoints={POINTS} onChangePoint={onChangePoint} {...props} />);
  return { onChangePoint, svg: screen.getByRole("img"), ...view };
}

function tickLabels(svg: HTMLElement): string[] {
  return Array.from(svg.querySelectorAll("g > text")).map((text) => text.textContent ?? "");
}

describe("BreakpointCurveEditor", () => {
  it("折れ点ごとに、入力値とスコアを名乗る動かせる点を置く", () => {
    renderEditor();
    const handles = screen.getAllByRole("slider");
    expect(handles).toHaveLength(POINTS.length);
    expect(handles[1]).toHaveAccessibleName("折れ点2（入力値10、スコア100）");
    expect(handles[1]).toHaveAttribute("aria-valuenow", "100");
  });

  it("左右キーは横軸の刻みで、上下キーはスコア1で動かし、Shiftを押すと10倍にする", () => {
    const { onChangePoint } = renderEditor();
    const step = niceStep(POINTS[1][0] - POINTS[0][0]);
    const handle = screen.getAllByRole("slider")[1];

    fireEvent.keyDown(handle, { key: "ArrowRight" });
    fireEvent.keyDown(handle, { key: "ArrowLeft", shiftKey: true });
    fireEvent.keyDown(handle, { key: "ArrowUp" });
    fireEvent.keyDown(handle, { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(handle, { key: "Enter" });

    expect(onChangePoint.mock.calls).toEqual([
      [1, 0, 10 + step],
      [1, 0, 10 - step * 10],
      [1, 1, 101],
      [1, 1, 90],
    ]);
  });

  it("ボタンを押したままドラッグすると、指の位置を横軸の刻み・整数のスコアへ丸めて渡し、動かしている間は値を出す", () => {
    const { onChangePoint, svg } = renderEditor();
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 160 }) as DOMRect;
    const handle = screen.getAllByRole("slider")[0];
    handle.setPointerCapture = vi.fn();

    fireEvent.pointerDown(handle, { pointerId: 1 });
    expect(svg).toHaveTextContent("0 → 0");

    // 描画域（左右の余白28を除く幅344・上下の余白を除く高さ104）の中央より少し右。横軸は刻みへ丸めて5になる。
    fireEvent.pointerMove(handle, { buttons: 1, clientX: 28 + 172 + 3, clientY: 28 + 52 });
    expect(onChangePoint.mock.calls).toEqual([
      [0, 0, 5],
      [0, 1, 50],
    ]);

    fireEvent.pointerUp(handle);
    expect(svg).not.toHaveTextContent("0 → 0");
  });

  it("ボタンを押していない移動では動かさない", () => {
    const { onChangePoint } = renderEditor();
    fireEvent.pointerMove(screen.getAllByRole("slider")[0], { buttons: 0, clientX: 100, clientY: 50 });
    expect(onChangePoint).not.toHaveBeenCalled();
  });

  it("参考点の範囲を渡すと、横軸を折れ点ではなくその範囲（前後1割の余白つき）で決める", () => {
    const { svg } = renderEditor({ referenceRange: { min: 100, max: 200 } });
    const labels = tickLabels(svg).map(Number);
    expect(labels.length).toBeGreaterThan(0);
    expect(Math.min(...labels)).toBeGreaterThanOrEqual(90);
    expect(Math.max(...labels)).toBeLessThanOrEqual(210);
    expect(labels).toContain(200);
  });

  it("参考点が無ければ、横軸は折れ点の範囲で決める", () => {
    const { svg } = renderEditor();
    const labels = tickLabels(svg).map(Number);
    expect(Math.min(...labels)).toBe(0);
    expect(Math.max(...labels)).toBe(10);
  });

  it("参考点が無く折れ点の横軸がすべて同じ値でも、その値に目盛りを置いて描く", () => {
    const { svg } = renderEditor({
      breakpoints: [
        [5, 0],
        [5, 100],
      ],
    });
    expect(tickLabels(svg)).toContain("5");
  });

  it("表示範囲の外にある延長は、しきい値以上なら左右に割合で出し、しきい値未満なら出さない", () => {
    const outside = 0.3;
    const { svg, unmount } = renderEditor({
      distribution: distribution({
        bins: [
          [-10, -5, outside],
          [2, 8, 1 - outside * 2],
          [20, 30, outside],
        ],
      }),
    });
    expect(svg).toHaveTextContent(`←${(outside * 100).toFixed(0)}%`);
    expect(svg).toHaveTextContent(`${(outside * 100).toFixed(0)}%→`);
    unmount();

    const tiny = OFF_RANGE_NOTICE_THRESHOLD / 2;
    const second = renderEditor({
      distribution: distribution({
        bins: [
          [-10, -5, tiny],
          [2, 8, 1 - tiny],
        ],
      }),
    });
    expect(second.svg).not.toHaveTextContent("←");
  });
});

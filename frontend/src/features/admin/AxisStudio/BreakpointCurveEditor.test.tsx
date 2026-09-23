import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BreakpointCurveEditor } from "./BreakpointCurveEditor";
import type { ValueDistribution } from "./scoreDistribution";

const BREAKPOINTS: [number, number][] = [
  [0, 0],
  [5, 100],
];

function editor(distribution: ValueDistribution | null, referenceRange?: { min: number; max: number }) {
  return render(
    <BreakpointCurveEditor
      breakpoints={BREAKPOINTS}
      onChangePoint={vi.fn()}
      referenceRange={referenceRange}
      distribution={distribution}
    />,
  );
}

function svg() {
  return screen.getByRole("img", { name: /折れ点の曲線プレビュー/ });
}

describe("BreakpointCurveEditor の分布の重ね描き", () => {
  it("分布が無くても曲線は描ける（分布は任意の追加情報）", () => {
    const { container } = editor(null);

    expect(svg()).toBeInTheDocument();
    expect(container.querySelectorAll("polyline")).toHaveLength(1);
    expect(container.querySelectorAll("rect")).toHaveLength(0);
  });

  it("階級ぶんの棒と、表示範囲に入る分位線を背景へ描く", () => {
    const { container } = editor({
      sample_ways: 100,
      total_km: 10,
      quantiles: { p10: 1, p50: 2, p90: 4, p99: 4.5 },
      bins: [
        [0, 1, 0.2],
        [1, 2, 0.5],
        [2, 3, 0.3],
      ],
      zero_share: 0,
    });

    expect(container.querySelectorAll("rect")).toHaveLength(3);
    // p10/p50/p90の3本のみ（p99は描かない）。
    expect(screen.getByText("p10")).toBeInTheDocument();
    expect(screen.getByText("p50")).toBeInTheDocument();
    expect(screen.getByText("p90")).toBeInTheDocument();
    expect(screen.queryByText("p99")).not.toBeInTheDocument();
  });

  it("表示範囲の外にある延長を割合として出す（黙って切らない）", () => {
    // 参考範囲0〜5に対し、延長の30%がその右側（20〜25）にある。
    editor(
      {
        sample_ways: 100,
        total_km: 10,
        quantiles: {},
        bins: [
          [0, 5, 0.7],
          [20, 25, 0.3],
        ],
        zero_share: 0,
      },
      { min: 0, max: 5 },
    );

    expect(screen.getByText("30%→")).toBeInTheDocument();
  });

  it("範囲外がごく僅かなら注意書きを出さない（毎回出ると意味を失う）", () => {
    editor(
      {
        sample_ways: 100,
        total_km: 10,
        quantiles: {},
        bins: [
          [0, 5, 0.995],
          [20, 25, 0.005],
        ],
        zero_share: 0,
      },
      { min: 0, max: 5 },
    );

    expect(screen.queryByText(/%→$/)).not.toBeInTheDocument();
  });

  it("折れ点は分布の背面に隠れず、操作できるsliderとして残る", () => {
    editor({
      sample_ways: 100,
      total_km: 10,
      quantiles: { p50: 2 },
      bins: [[0, 5, 1.0]],
      zero_share: 0,
    });

    expect(screen.getAllByRole("slider")).toHaveLength(BREAKPOINTS.length);
  });
});

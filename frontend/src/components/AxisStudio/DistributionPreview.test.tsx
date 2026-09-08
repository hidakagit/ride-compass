import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DistributionPreview } from "./DistributionPreview";
import type { ValueDistribution } from "./scoreDistribution";

const BP: [number, number][] = [
  [0, 0],
  [4, 100],
];

function dist(bins: [number, number, number][]): ValueDistribution {
  return { sample_ways: 1722, total_km: 254.1, quantiles: { p50: 16.4 }, bins, zero_share: 0.01 };
}

describe("DistributionPreview", () => {
  it("読込中・分布なし・失敗をそれぞれ言葉で示す（黙って空にしない）", () => {
    const { rerender } = render(
      <DistributionPreview distribution={null} breakpoints={BP} loading error={null} />,
    );
    expect(screen.getByText(/集計中/)).toBeInTheDocument();

    rerender(<DistributionPreview distribution={null} breakpoints={BP} loading={false} error={null} />);
    expect(screen.getByText(/材料を選ぶと/)).toBeInTheDocument();

    rerender(
      <DistributionPreview distribution={null} breakpoints={BP} loading={false} error="取得に失敗しました" />,
    );
    expect(screen.getByText("取得に失敗しました")).toBeInTheDocument();
  });

  it("折れ点が実データに合っていないと警告を出す（満点への張り付き）", () => {
    // 生値がすべて折れ点の上限を超える＝全部が満点になる分布。
    render(
      <DistributionPreview distribution={dist([[10, 12, 1.0]])} breakpoints={BP} loading={false} error={null} />,
    );
    expect(screen.getByText(/満点に張り付きます/)).toBeInTheDocument();
    expect(screen.getByText("100.0%")).toBeInTheDocument();
  });

  it("散らばっていれば警告を出さず、母集団の規模を添える", () => {
    render(
      <DistributionPreview
        distribution={dist([
          [0, 0.1, 0.4],
          [1, 1.2, 0.3],
          [3, 3.2, 0.3],
        ])}
        breakpoints={BP}
        loading={false}
        error={null}
      />,
    );
    expect(screen.queryByText(/満点に張り付きます/)).not.toBeInTheDocument();
    expect(screen.getByText(/1,722本/)).toBeInTheDocument();
    expect(screen.getByText(/254.1km/)).toBeInTheDocument();
  });
});

/**
 * `DistributionPreview.tsx`——折れ点での得点分布を、状態（失敗・集計中・未選択・Way単位で値が定まらない・分布あり）
 * ごとに1つだけ出すこと。分布があれば帯ごとの割合と分位、警告を並べる（点数が届くまでは帯の代わりに理由）。
 *
 * ここで見ないもの:
 * - 帯への振り分けと警告の条件 → `scoreDistribution.test.ts`（期待値はそこの関数から引く）
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DistributionPreview } from "./DistributionPreview";
import { distributionWarnings, scoreBands, type ValueDistribution } from "./scoreDistribution";

/** 既定の分布（2階級）の、backendが返す階級ごとの点数。 */
const SCORES = [0, 50];

function distribution(overrides: Partial<ValueDistribution> = {}): ValueDistribution {
  return {
    sample_ways: 1234,
    total_km: 56.5,
    quantiles: { p99: 99, p10: 10, p50: 50 },
    bins: [
      [0, 0, 0.25],
      [40, 60, 0.75],
    ],
    zero_share: 0.25,
    ...overrides,
  };
}

function renderPreview(props: Partial<Parameters<typeof DistributionPreview>[0]>) {
  render(
    <DistributionPreview
      distribution={null}
      binScores={SCORES}
      scoresFailed={false}
      loading={false}
      error={null}
      {...props}
    />,
  );
  return screen.getByRole("region", { name: "折れ点の効き方" });
}

describe("DistributionPreview", () => {
  it.each([
    [
      "失敗したら、分布があっても理由だけ",
      { error: "分布の取得に失敗しました", distribution: distribution() },
      "分布の取得に失敗しました",
      "抽選した",
    ],
    ["まだ分布が無いまま集計中なら、集計中", { loading: true }, "実データを集計中", "材料を選ぶと"],
    ["集計し直している間は、手元の分布", { loading: true, distribution: distribution() }, "1,234本", "集計中"],
    ["分布が無く集計もしていなければ、材料を選ぶ促し", {}, "材料を選ぶと", "集計中"],
    [
      "抽選した道が1本も値を持たなければ、0%の帯ではなく理由",
      { distribution: distribution({ sample_ways: 0 }) },
      "Way単位では値が定まらない",
      "%",
    ],
    ["点数が届いていなければ、0%の帯ではなく計算中", { distribution: distribution(), binScores: null }, "計算中", "%"],
    [
      "点数を取れなければ、0%の帯ではなく失敗",
      { distribution: distribution(), binScores: null, scoresFailed: true },
      "取得できませんでした",
      "%",
    ],
  ])("%sを出す", (_case, props, shown, hidden) => {
    const region = renderPreview(props);
    expect(region).toHaveTextContent(shown);
    expect(region).not.toHaveTextContent(hidden);
  });

  it("分布があれば、抽選の規模と、帯ごとの割合（小数1桁）を帯の並びどおりに出す", () => {
    const value = distribution();
    const region = renderPreview({ distribution: value });

    expect(region).toHaveTextContent("1,234本");
    expect(region).toHaveTextContent("56.5km");
    const bands = scoreBands(value, SCORES)!;
    expect(bands.length).toBeGreaterThan(0);
    for (const band of bands) {
      const row = within(region).getByText(band.label).parentElement!;
      expect(row).toHaveTextContent(`${(band.share * 100).toFixed(1)}%`);
    }
  });

  it("分位は小さい順に、届いたものだけを並べる", () => {
    const region = renderPreview({ distribution: distribution() });
    expect(within(region).getByText(/材料の合成値/)).toHaveTextContent(/p10=10\s+p50=50\s+p99=99/);
  });

  it("帯の割合から出る警告を、そのまま並べる", () => {
    const value = distribution({ bins: [[200, 200, 1]] });
    const warnings = distributionWarnings(scoreBands(value, [100])!);
    expect(warnings.length).toBeGreaterThan(0);

    const region = renderPreview({ distribution: value, binScores: [100] });
    for (const warning of warnings) expect(within(region).getByText(warning)).toBeInTheDocument();
  });
});

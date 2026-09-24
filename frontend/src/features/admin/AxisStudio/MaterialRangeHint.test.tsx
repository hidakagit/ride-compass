/**
 * `MaterialRangeHint.tsx`——材料の値が実データで取る分位（中央と上側）を1行で出し、出せないときは何も出さないこと。
 *
 * ここで見ないもの:
 * - 分布の取得と共有 → `useMaterialDistribution.test.ts`
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MaterialDistribution } from "@/features/admin/axisPreviewApi";

const hook = vi.hoisted(() => ({ distribution: null as MaterialDistribution | null }));
vi.mock("@/features/admin/useMaterialDistribution", () => ({
  useMaterialDistribution: () => ({ distribution: hook.distribution, loading: false }),
}));

import { MaterialRangeHint } from "./MaterialRangeHint";

function distribution(overrides: Partial<MaterialDistribution>): MaterialDistribution {
  return { available: true, sample_ways: 1, total_km: 1, quantiles: {}, bins: [], zero_share: 0, ...overrides };
}

function renderHint(value: MaterialDistribution | null, unit?: string) {
  hook.distribution = value;
  return render(<MaterialRangeHint materialId="num_a" unit={unit} />);
}

describe("MaterialRangeHint", () => {
  it("0の割合があれば、百分率に丸めて添える。無ければ添えない", () => {
    const { unmount } = renderHint(distribution({ quantiles: { p50: 5 }, zero_share: 0.126 }));
    expect(screen.getByText(/実データ/)).toHaveTextContent("ゼロ13%");
    unmount();

    renderHint(distribution({ quantiles: { p50: 5 }, zero_share: 0 }));
    expect(screen.getByText(/実データ/)).not.toHaveTextContent("ゼロ");
  });

  it.each([
    ["分布が無い", null],
    ["backendが出せないと答えた", distribution({ available: false, quantiles: { p50: 5 } })],
    ["出す分位が1つも無い", distribution({ quantiles: { p10: 1 } })],
  ])("%sときは何も出さない", (_case, value) => {
    const { container } = renderHint(value);
    expect(container).toBeEmptyDOMElement();
  });
});

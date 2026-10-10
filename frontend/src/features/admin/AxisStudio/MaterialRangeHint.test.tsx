/**
 * `MaterialRangeHint.tsx`——材料の値が実データで取る分位（中央と上側）を1行で出し、出せないときは何も出さないこと。
 *
 * 差し替えたもの: 材料の分布の応答（網の層）。
 *
 * ここで見ないもの:
 * - 分布の取得と共有 → `useMaterialDistribution.test.ts`
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MaterialDistribution } from "@/features/admin/adminApi";
import { settle } from "@/testing/settle";
import { onSameOrigin } from "@/testing/backendServer";

import { MaterialRangeHint } from "./MaterialRangeHint";

function distribution(overrides: Partial<MaterialDistribution>): MaterialDistribution {
  return { available: true, quantiles: {}, zero_share: 0, ...overrides };
}

/** 材料`materialId`の分布の取得に`reply`を返して描く（取れた分布は材料ごとに覚えられるので、描き直すなら材料を変える）。 */
function renderHint(reply: Response, materialId = "num_a") {
  onSameOrigin("GET", "/admin/api/material-catalog/:materialId/distribution", () => reply.clone());
  return render(<MaterialRangeHint materialId={materialId} unit={undefined} />);
}

describe("MaterialRangeHint", () => {
  it("0の割合があれば、百分率に丸めて添える。無ければ添えない", async () => {
    const { unmount } = renderHint(Response.json(distribution({ quantiles: { p50: 5 }, zero_share: 0.126 })));
    expect(await screen.findByText(/実データ/)).toHaveTextContent("ゼロ13%");
    unmount();

    renderHint(Response.json(distribution({ quantiles: { p50: 5 }, zero_share: 0 })), "num_b");
    expect(await screen.findByText(/実データ/)).not.toHaveTextContent("ゼロ");
  });

  it.each([
    ["分布を取れない", new Response(null, { status: 500 })],
    ["backendが出せないと答えた", Response.json(distribution({ available: false, quantiles: { p50: 5 } }))],
    ["出す分位が1つも無い", Response.json(distribution({ quantiles: { p10: 1 } }))],
  ])("%sときは何も出さない", async (_case, reply) => {
    const { container } = renderHint(reply);
    await settle();
    expect(container).toBeEmptyDOMElement();
  });
});

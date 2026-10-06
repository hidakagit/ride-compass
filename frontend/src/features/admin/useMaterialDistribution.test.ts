/**
 * `useMaterialDistribution.ts`——材料1件の値の分布を取り、同じ材料は（取れなかったことも含めて）
 * 1回しか取りに行かないこと。
 *
 * ここで見ないもの:
 * - 分布を画面にどう出すか → `AxisStudio/MaterialRangeHint.test.tsx`
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { heldReplies, inTurn, onSameOrigin } from "@/testing/backendServer";

import type { MaterialDistribution } from "./adminApi";
import { useMaterialDistribution } from "./useMaterialDistribution";

const DISTRIBUTION = "/admin/api/material-catalog/:materialId/distribution";

function distribution(p50: number): MaterialDistribution {
  return { available: true, quantiles: { p50 }, zero_share: 0 };
}

/** 取り直しが起きていれば応答が届くだけの間をおく（起きないことを確かめるため）。 */
const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 50)));

describe("useMaterialDistribution", () => {
  it("材料が無ければ取りに行かない", async () => {
    const { result } = renderHook(() => useMaterialDistribution(undefined));
    await act(async () => {});
    expect(result.current).toBeNull();
  });

  it("取っている間は分布なしで、届いたら分布を返す", async () => {
    const held = heldReplies();
    onSameOrigin("GET", DISTRIBUTION, held.reply);
    const { result } = renderHook(() => useMaterialDistribution("m_loading"));

    await waitFor(() => expect(held.arrived()).toBe(1));
    expect(result.current).toBeNull();
    await held.answer(0, Response.json(distribution(5)));
    await waitFor(() => expect(result.current).toEqual(distribution(5)));
  });

  it("取れなかったら分布なしで返し、同じ材料を別の場所が選んでも取り直さない", async () => {
    onSameOrigin("GET", DISTRIBUTION, inTurn(new Response(null, { status: 500 }), Response.json(distribution(7))));
    const first = renderHook(() => useMaterialDistribution("m_failing"));
    await settle();
    expect(first.result.current).toBeNull();

    const second = renderHook(() => useMaterialDistribution("m_failing"));
    await settle();
    expect(second.result.current).toBeNull();
  });
});

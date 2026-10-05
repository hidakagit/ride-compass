/**
 * `useMaterialValues.ts`——材料の実データの値一覧を取り、「候補が無い（0件）」と「候補を出せなかった」を
 * 区別して返すこと。材料を切り替えた直後に、前の材料の値を一瞬でも返さないこと。
 *
 * ここで見ないもの:
 * - 候補を画面でどう使うか（選択式か自由入力か） → `AxisStudio/AxisScoringSection.test.tsx`
 */
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { getMaterialValues } from "@/features/admin/adminApi";
import { heldReplies, onSameOrigin } from "@/testing/backendServer";

import { useMaterialValues } from "./useMaterialValues";

type MaterialValuesResponse = Awaited<ReturnType<typeof getMaterialValues>>;

const VALUES = "/admin/api/material-catalog/:materialId/values";

function response(values: string[], available = true): MaterialValuesResponse {
  return { available, values: values.map((value) => ({ value, label: value })) };
}

describe("useMaterialValues", () => {
  it("材料が無ければ取りに行かず、候補なし・出せなかったわけでもない", () => {
    const { result } = renderHook(() => useMaterialValues(null));
    expect(result.current).toEqual({ values: [], unavailable: false });
  });

  it("選んだ材料の値一覧を返す", async () => {
    onSameOrigin("GET", VALUES, ({ path }) =>
      Response.json(path.includes("/cat_a/") ? response(["primary", "track"]) : response(["other"])),
    );
    const { result } = renderHook(() => useMaterialValues("cat_a"));

    await waitFor(() => expect(result.current.values.map((v) => v.value)).toEqual(["primary", "track"]));
    expect(result.current.unavailable).toBe(false);
  });

  it.each([
    ["backendが値一覧を出せない（DB障害等）と答えた", () => Response.json(response([], false))],
    ["取得に失敗した", () => new Response(null, { status: 500 })],
  ])("%sら、出せなかったとして返す", async (_case, reply) => {
    onSameOrigin("GET", VALUES, reply);
    const { result } = renderHook(() => useMaterialValues("cat_a"));
    await waitFor(() => expect(result.current).toEqual({ values: [], unavailable: true }));
  });

  it("材料を切り替えた直後は、前の材料の値を返さない", async () => {
    const held = heldReplies();
    onSameOrigin("GET", VALUES, ({ path }) =>
      path.includes("/a/") ? Response.json(response(["a_value"])) : held.reply(),
    );
    const { result, rerender } = renderHook(({ id }) => useMaterialValues(id), { initialProps: { id: "a" } });
    await waitFor(() => expect(result.current.values.map((v) => v.value)).toEqual(["a_value"]));

    rerender({ id: "b" });
    expect(result.current).toEqual({ values: [], unavailable: false });
  });
});

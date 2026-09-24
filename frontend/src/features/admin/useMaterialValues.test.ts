/**
 * `useMaterialValues.ts`——材料の実データの値一覧を取り、「候補が無い（0件）」と「候補を出せなかった」を
 * 区別して返すこと。材料を切り替えた直後に、前の材料の値を一瞬でも返さないこと。
 *
 * ここで見ないもの:
 * - 候補を画面でどう使うか（選択式か自由入力か） → `AxisStudio/AxisScoringSection.test.tsx`
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MaterialValuesResponse } from "@/types/route";

const api = vi.hoisted(() => ({ getMaterialValues: vi.fn() }));
vi.mock("@/services/materialCatalogApi", () => ({ getMaterialValues: api.getMaterialValues }));

import { useMaterialValues } from "./useMaterialValues";

function response(values: string[], available = true): MaterialValuesResponse {
  return { available, values: values.map((value) => ({ value, label: value })) };
}

beforeEach(() => {
  api.getMaterialValues.mockReset();
});

describe("useMaterialValues", () => {
  it("材料が無ければ取りに行かず、候補なし・出せなかったわけでもない", () => {
    const { result } = renderHook(() => useMaterialValues(null));
    expect(api.getMaterialValues).not.toHaveBeenCalled();
    expect(result.current).toEqual({ values: [], unavailable: false });
  });

  it("取れた値一覧を返す", async () => {
    api.getMaterialValues.mockResolvedValue(response(["primary", "track"]));
    const { result } = renderHook(() => useMaterialValues("cat_a"));

    await waitFor(() => expect(result.current.values.map((v) => v.value)).toEqual(["primary", "track"]));
    expect(result.current.unavailable).toBe(false);
    expect(api.getMaterialValues).toHaveBeenCalledWith("cat_a");
  });

  it("backendが値一覧を出せない（DB未接続等）と答えたら、出せなかったとして返す", async () => {
    api.getMaterialValues.mockResolvedValue(response([], false));
    const { result } = renderHook(() => useMaterialValues("cat_a"));
    await waitFor(() => expect(result.current.unavailable).toBe(true));
    expect(result.current.values).toEqual([]);
  });

  it("取得に失敗したら、出せなかったとして返す", async () => {
    api.getMaterialValues.mockRejectedValue(new Error("材料の値一覧の取得に失敗しました"));
    const { result } = renderHook(() => useMaterialValues("cat_a"));
    await waitFor(() => expect(result.current).toEqual({ values: [], unavailable: true }));
  });

  it("材料を切り替えた直後は前の材料の値を返さず、後から届いた前の材料の答えも捨てる", async () => {
    let answerFirst!: (value: MaterialValuesResponse) => void;
    api.getMaterialValues
      .mockReturnValueOnce(Promise.resolve(response(["a_value"])))
      .mockReturnValueOnce(new Promise<MaterialValuesResponse>((resolve) => (answerFirst = resolve)))
      .mockReturnValueOnce(Promise.resolve(response(["c_value"])));
    const { result, rerender } = renderHook(({ id }) => useMaterialValues(id), { initialProps: { id: "a" } });
    await waitFor(() => expect(result.current.values.map((v) => v.value)).toEqual(["a_value"]));

    rerender({ id: "b" });
    expect(result.current).toEqual({ values: [], unavailable: false });

    rerender({ id: "c" });
    await waitFor(() => expect(result.current.values.map((v) => v.value)).toEqual(["c_value"]));
    await act(async () => answerFirst(response(["b_value"])));
    expect(result.current.values.map((v) => v.value)).toEqual(["c_value"]);
  });

  it("材料を切り替えたら、前の材料の取得が後から失敗しても、今の材料の値を出せなかったことにしない", async () => {
    let failFirst!: (reason: unknown) => void;
    api.getMaterialValues
      .mockReturnValueOnce(new Promise<MaterialValuesResponse>((_resolve, reject) => (failFirst = reject)))
      .mockResolvedValueOnce(response(["b_value"]));
    const { result, rerender } = renderHook(({ id }) => useMaterialValues(id), { initialProps: { id: "a" } });

    rerender({ id: "b" });
    await waitFor(() => expect(result.current.values.map((v) => v.value)).toEqual(["b_value"]));
    await act(async () => failFirst(new Error("遅れた失敗")));
    expect(result.current).toEqual({ values: [expect.objectContaining({ value: "b_value" })], unavailable: false });
  });
});

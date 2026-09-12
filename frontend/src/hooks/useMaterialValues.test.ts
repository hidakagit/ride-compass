import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MaterialValuesResponse } from "@/types/route";

vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialValues: vi.fn(),
}));

import { getMaterialValues } from "@/services/materialCatalogApi";
import { useMaterialValues } from "./useMaterialValues";

describe("useMaterialValues", () => {
  it("materialIdがnullの間はAPIを呼ばず空配列を返す", () => {
    const { result } = renderHook(() => useMaterialValues(null));

    expect(result.current.values).toEqual([]);
    expect(getMaterialValues).not.toHaveBeenCalled();
  });

  it("フェッチが完了すると値一覧（value/labelの組）を返す", async () => {
    vi.mocked(getMaterialValues).mockResolvedValue({
      available: true,
      values: [
        { value: "residential", label: "住宅街の道路" },
        { value: "primary", label: "主要幹線道路" },
      ],
    } satisfies MaterialValuesResponse);

    const { result } = renderHook(() => useMaterialValues("highway"));

    await waitFor(() =>
      expect(result.current.values).toEqual([
        { value: "residential", label: "住宅街の道路" },
        { value: "primary", label: "主要幹線道路" },
      ]),
    );
    expect(getMaterialValues).toHaveBeenCalledWith("highway");
  });

  it("フェッチ失敗時は空配列で、取得できなかったことを印として返す", async () => {
    vi.mocked(getMaterialValues).mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useMaterialValues("highway"));

    await waitFor(() => expect(result.current.unavailable).toBe(true));
    expect(result.current.values).toEqual([]);
  });

  it("available=falseは「候補が無い」ではなく「出せなかった」として返す", async () => {
    // 同じ空配列へ倒すと、DBのタイムアウトが「この材料には値が無い」として静かに表示される。
    vi.mocked(getMaterialValues).mockResolvedValue({
      available: false,
      values: [],
    } satisfies MaterialValuesResponse);

    const { result } = renderHook(() => useMaterialValues("highway"));

    await waitFor(() => expect(result.current.unavailable).toBe(true));
  });

  it("materialIdが変わると値一覧を引き継がずリセットしてから再取得する", async () => {
    vi.mocked(getMaterialValues).mockImplementation(async (materialId: string) => ({
      available: true,
      values:
        materialId === "highway"
          ? [{ value: "residential", label: "住宅街の道路" }]
          : [{ value: "good", label: "良好" }],
    }));

    const { result, rerender } = renderHook(({ materialId }) => useMaterialValues(materialId), {
      initialProps: { materialId: "highway" as string | null },
    });

    await waitFor(() => expect(result.current.values).toEqual([{ value: "residential", label: "住宅街の道路" }]));

    rerender({ materialId: "smoothness" });

    // 前の材料（highway）の値一覧を一瞬でも引きずらない。
    expect(result.current.values).toEqual([]);
    await waitFor(() => expect(result.current.values).toEqual([{ value: "good", label: "良好" }]));
  });
});

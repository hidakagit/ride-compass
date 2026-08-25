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

    expect(result.current).toEqual([]);
    expect(getMaterialValues).not.toHaveBeenCalled();
  });

  it("フェッチが完了すると値一覧を返す", async () => {
    vi.mocked(getMaterialValues).mockResolvedValue({
      values: ["residential", "primary"],
    } satisfies MaterialValuesResponse);

    const { result } = renderHook(() => useMaterialValues("highway"));

    await waitFor(() => expect(result.current).toEqual(["residential", "primary"]));
    expect(getMaterialValues).toHaveBeenCalledWith("highway");
  });

  it("フェッチ失敗時は空配列のまま", async () => {
    vi.mocked(getMaterialValues).mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useMaterialValues("highway"));

    await waitFor(() => expect(getMaterialValues).toHaveBeenCalled());
    expect(result.current).toEqual([]);
  });

  it("materialIdが変わると値一覧を引き継がずリセットしてから再取得する", async () => {
    vi.mocked(getMaterialValues).mockImplementation(async (materialId: string) => ({
      values: materialId === "highway" ? ["residential"] : ["good"],
    }));

    const { result, rerender } = renderHook(({ materialId }) => useMaterialValues(materialId), {
      initialProps: { materialId: "highway" as string | null },
    });

    await waitFor(() => expect(result.current).toEqual(["residential"]));

    rerender({ materialId: "smoothness" });

    // 前の材料（highway）の値一覧を一瞬でも引きずらない。
    expect(result.current).toEqual([]);
    await waitFor(() => expect(result.current).toEqual(["good"]));
  });
});

import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MaterialCatalogResponse } from "@/types/route";

vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn(),
}));

import { getMaterialCatalog } from "@/services/materialCatalogApi";
import { useMaterialCatalog } from "./useMaterialCatalog";

function catalogResponse(): MaterialCatalogResponse {
  return {
    materials: [
      {
        material_id: "num_a",
        label: "数値の材料 - num_a",
        name: "数値の材料",
        description: "テスト用。",
        dtype: "numeric",
        unit: "%",
        reference_points: [{ label: "平坦", value: 0 }],
      },
      {
        material_id: "bool_a",
        label: "真偽の材料 - bool_a",
        name: "真偽の材料",
        description: "テスト用。",
        dtype: "boolean",
        unit: "",
        reference_points: [],
      },
    ],
  };
}

describe("useMaterialCatalog", () => {
  it("取得した材料を、画面が使う形へ移して返す", async () => {
    vi.mocked(getMaterialCatalog).mockResolvedValue(catalogResponse());

    const { result } = renderHook(() => useMaterialCatalog());

    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.materials).toEqual([
      {
        id: "num_a",
        label: "数値の材料 - num_a",
        name: "数値の材料",
        description: "テスト用。",
        dtype: "numeric",
        unit: "%",
        referencePoints: [{ label: "平坦", value: 0 }],
      },
      {
        id: "bool_a",
        label: "真偽の材料 - bool_a",
        name: "真偽の材料",
        description: "テスト用。",
        dtype: "boolean",
        unit: "",
        referencePoints: [],
      },
    ]);
  });

  it("取得できた0件は、まだ取得できていない状態と区別できる", async () => {
    vi.mocked(getMaterialCatalog).mockResolvedValue({ materials: [] });

    const { result } = renderHook(() => useMaterialCatalog());

    await waitFor(() => expect(result.current).toEqual({ materials: [], loaded: true }));
  });

  it("取得に失敗しても空のままで、古い一覧を見せない", async () => {
    vi.mocked(getMaterialCatalog).mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useMaterialCatalog());

    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.materials).toEqual([]);
  });

  // 「取得前は空」テストより前に置くこと——あちらは解決しないPromiseをモジュール内の
  // 実行中スロットへ残すため、後で実行するとこのテストの新規フェッチがそれへ相乗りして
  // 解決しなくなる。
  it("同時にマウントしても、実行中のフェッチを共有して1回しか取りに行かない", async () => {
    vi.mocked(getMaterialCatalog).mockClear();
    vi.mocked(getMaterialCatalog).mockResolvedValue(catalogResponse());

    const first = renderHook(() => useMaterialCatalog());
    const second = renderHook(() => useMaterialCatalog());

    await waitFor(() => {
      expect(first.result.current.materials).toHaveLength(2);
      expect(second.result.current.materials).toHaveLength(2);
    });
    expect(getMaterialCatalog).toHaveBeenCalledTimes(1);
  });

  it("取得前はloadedが立たない", () => {
    vi.mocked(getMaterialCatalog).mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useMaterialCatalog());

    expect(result.current).toEqual({ materials: [], loaded: false });
  });
});

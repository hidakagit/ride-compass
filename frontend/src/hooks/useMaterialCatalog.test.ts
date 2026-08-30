import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MaterialCatalogResponse } from "@/types/route";

// 実バグ修正の回帰テスト（デッドコード監査、2026-08-25）: useAxisCatalog.tsで既に修正した
// 同型のバグ（`response.axes.length > 0`ガードにより「まだ取得中/取得失敗」と
// 「取得成功したが0件」を同一視していた）が、useMaterialCatalog.tsにも残っていた
// （`response.materials.length > 0`）。RouteSettingsPanel.test.tsx/useAxisCatalog.test.tsと
// 同じモック方針。
vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn(),
}));

import { getMaterialCatalog } from "@/services/materialCatalogApi";
import { AXIS_MATERIAL_OPTIONS } from "@/lib/axisMaterialsCatalog";
import { useMaterialCatalog } from "./useMaterialCatalog";

function catalogResponse(): MaterialCatalogResponse {
  return {
    materials: [
      { material_id: "gradient_percent", label: "勾配%（符号付き）", description: "勾配（%）。", dtype: "numeric" },
      // 静的フォールバック（AXIS_MATERIAL_OPTIONS）には無い、backend側だけへ新規追加された材料。
      { material_id: "new_material", label: "新規材料テスト", description: "テスト用の材料。", dtype: "boolean" },
    ],
  };
}

describe("useMaterialCatalog", () => {
  it("実行時フェッチが完了すると、フォールバックに無い新規材料を含む一覧を返す", async () => {
    vi.mocked(getMaterialCatalog).mockResolvedValue(catalogResponse());

    const { result } = renderHook(() => useMaterialCatalog());

    await waitFor(() => {
      expect(result.current.some((m) => m.id === "new_material")).toBe(true);
    });
    expect(result.current).toEqual([
      { id: "gradient_percent", label: "勾配%（符号付き）", description: "勾配（%）。", dtype: "numeric" },
      { id: "new_material", label: "新規材料テスト", description: "テスト用の材料。", dtype: "boolean" },
    ]);
  });

  // 実バグの回帰テスト本体: 取得成功したがmaterialsが0件のレスポンスは、静的フォールバック
  // へ戻さずそのまま空を返す（0件success ≠ フォールバック、useAxisCatalog.test.tsの
  // 「全軸非公開でaxesが0件のレスポンスは、静的フォールバックへ戻さずそのまま空を返す」と
  // 同じ形の回帰テスト）。修正前は`response.materials.length > 0`ガードにより、0件成功時も
  // AXIS_MATERIAL_OPTIONS（既存9材料）が残り続けていた。
  it("取得成功したがmaterialsが0件のレスポンスは、静的フォールバックへ戻さずそのまま空を返す", async () => {
    vi.mocked(getMaterialCatalog).mockResolvedValue({ materials: [] });

    const { result } = renderHook(() => useMaterialCatalog());

    await waitFor(() => expect(result.current).toEqual([]));
  });

  it("フェッチ失敗時は静的フォールバック（AXIS_MATERIAL_OPTIONS）を返す", async () => {
    vi.mocked(getMaterialCatalog).mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useMaterialCatalog());

    // フォールバックは初期値としてすでにセットされているため、フェッチが失敗して
    // 何も変わらないことを確認する（catchブロックが状態を書き換えない）。
    await waitFor(() => expect(vi.mocked(getMaterialCatalog)).toHaveBeenCalled());
    expect(result.current).toEqual(AXIS_MATERIAL_OPTIONS);
  });

  // 改善計画T470: useAxisCatalog.tsの同時フェッチ排除（inFlightCatalogFetch）と同じ
  // パターンをuseMaterialCatalogへも適用した回帰テスト。同時にマウントした2箇所が
  // 同じリクエストを共有し、GET /api/material-catalogは1回しか発火しない。
  // 注意: 「マウント直後（フェッチ未解決）」テスト（下記）より前に置くこと——
  // あちらは永久に解決しないPromiseをinFlightMaterialCatalogFetchへ残すため、
  // 後で実行すると本テストの新規フェッチがそのPromiseへ相乗りしてしまい解決しない。
  it("複数箇所が同時にマウントしても、実行中のフェッチを共有し1回しか発火しない", async () => {
    vi.mocked(getMaterialCatalog).mockClear();
    vi.mocked(getMaterialCatalog).mockResolvedValue(catalogResponse());

    const first = renderHook(() => useMaterialCatalog());
    const second = renderHook(() => useMaterialCatalog());

    await waitFor(() => {
      expect(first.result.current.some((m) => m.id === "new_material")).toBe(true);
      expect(second.result.current.some((m) => m.id === "new_material")).toBe(true);
    });
    expect(getMaterialCatalog).toHaveBeenCalledTimes(1);
  });

  it("マウント直後（フェッチ未解決）は静的フォールバックを返す", () => {
    vi.mocked(getMaterialCatalog).mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useMaterialCatalog());

    expect(result.current).toEqual(AXIS_MATERIAL_OPTIONS);
  });
});

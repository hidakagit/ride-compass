import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDynamicWayValues } from "./useDynamicWayValues";
import { fetchDynamicWayValues } from "@/services/regionApi";
import type { MapViewport } from "@/components/Map/windLayer";

// 改善計画T423（T411の実施）: 旧hooks/useWindAxisPenalties.test.tsを材料id駆動へ汎用化した。
vi.mock("@/services/regionApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/regionApi")>("@/services/regionApi");
  return {
    ...actual,
    fetchDynamicWayValues: vi.fn(),
  };
});

const VIEWPORT: MapViewport = { west: 139.699, south: 35.699, east: 139.701, north: 35.701, zoom: 14 };

describe("useDynamicWayValues（改善計画T405→T423: way_id→動的値配信層のフェッチ・状態管理）", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("enabled=falseの間はフェッチせず、空の結果を返す", () => {
    const { result } = renderHook(() => useDynamicWayValues("wind", false, VIEWPORT, 0, undefined));
    expect(fetchDynamicWayValues).not.toHaveBeenCalled();
    expect(result.current.values.size).toBe(0);
    expect(result.current.byTile).toEqual([]);
  });

  it("viewportがnullの間はフェッチしない", () => {
    const { result } = renderHook(() => useDynamicWayValues("wind", true, null, 0, undefined));
    expect(fetchDynamicWayValues).not.toHaveBeenCalled();
    expect(result.current.values.size).toBe(0);
  });

  it("enabled=trueで、現在のビューポートを覆うタイル分をmaterial_id付きでフェッチし統合した結果を返す", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ "1": 2.5, "2": -1.0 });
    const at = new Date("2026-08-30T09:00:00Z");

    const { result } = renderHook(() => useDynamicWayValues("wind", true, VIEWPORT, 90, at));

    await waitFor(() => expect(result.current.values.size).toBe(2));
    expect(result.current.values.get(1)).toBe(2.5);
    expect(result.current.values.get(2)).toBe(-1.0);
    expect(fetchDynamicWayValues).toHaveBeenCalledWith("wind", 14, 14549, 6450, 90, at);
  });

  it("material_idが異なれば別々の値としてフェッチする（gradientの例）", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ "3": 4.5 });

    const { result } = renderHook(() => useDynamicWayValues("gradient", true, VIEWPORT, 45, undefined));

    await waitFor(() => expect(result.current.values.size).toBe(1));
    expect(fetchDynamicWayValues).toHaveBeenCalledWith("gradient", 14, 14549, 6450, 45, undefined);
  });

  it("byTileにタイルごとの生応答を保持する（gridFillのタイル単位集計向け）", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ "1": 2.5 });

    const { result } = renderHook(() => useDynamicWayValues("gradient", true, VIEWPORT, 0, undefined));

    await waitFor(() => expect(result.current.byTile.length).toBe(1));
    expect(result.current.byTile[0].tile).toEqual({ z: 14, x: 14549, y: 6450 });
    expect(result.current.byTile[0].values).toEqual({ "1": 2.5 });
  });

  it("OFFへ切り替えると結果を空へ戻す", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ "1": 2.5 });

    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useDynamicWayValues("wind", enabled, VIEWPORT, 0, undefined),
      { initialProps: { enabled: true } },
    );

    await waitFor(() => expect(result.current.values.size).toBe(1));

    rerender({ enabled: false });

    await waitFor(() => expect(result.current.values.size).toBe(0));
  });

  it("タイル取得が失敗しても（fetchDynamicWayValuesが空オブジェクトで解決する前提で）例外を投げず空の結果に収束する", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({});

    const { result } = renderHook(() => useDynamicWayValues("wind", true, VIEWPORT, 0, undefined));

    await waitFor(() => expect(fetchDynamicWayValues).toHaveBeenCalled());
    expect(result.current.values.size).toBe(0);
  });
});

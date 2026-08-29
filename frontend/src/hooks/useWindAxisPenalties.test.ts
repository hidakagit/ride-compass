import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useWindAxisPenalties } from "./useWindAxisPenalties";
import { fetchWindWayPenalties } from "@/services/regionApi";
import type { MapViewport } from "@/components/Map/windLayer";

vi.mock("@/services/regionApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/regionApi")>("@/services/regionApi");
  return {
    ...actual,
    fetchWindWayPenalties: vi.fn(),
  };
});

const VIEWPORT: MapViewport = { west: 139.699, south: 35.699, east: 139.701, north: 35.701, zoom: 14 };

describe("useWindAxisPenalties（改善計画T405: way_id→wind_penalty配信層のフェッチ・状態管理）", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("enabled=falseの間はフェッチせず、空のMapを返す", () => {
    const { result } = renderHook(() => useWindAxisPenalties(false, VIEWPORT));
    expect(fetchWindWayPenalties).not.toHaveBeenCalled();
    expect(result.current.size).toBe(0);
  });

  it("viewportがnullの間はフェッチしない", () => {
    const { result } = renderHook(() => useWindAxisPenalties(true, null));
    expect(fetchWindWayPenalties).not.toHaveBeenCalled();
    expect(result.current.size).toBe(0);
  });

  it("enabled=trueで、現在のビューポートを覆うタイル分をフェッチし統合した結果を返す", async () => {
    vi.mocked(fetchWindWayPenalties).mockResolvedValue({ "1": 2.5, "2": -1.0 });

    const { result } = renderHook(() => useWindAxisPenalties(true, VIEWPORT));

    await waitFor(() => expect(result.current.size).toBe(2));
    expect(result.current.get(1)).toBe(2.5);
    expect(result.current.get(2)).toBe(-1.0);
    expect(fetchWindWayPenalties).toHaveBeenCalledWith(14, 14549, 6450);
  });

  it("OFFへ切り替えると結果を空へ戻す", async () => {
    vi.mocked(fetchWindWayPenalties).mockResolvedValue({ "1": 2.5 });

    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useWindAxisPenalties(enabled, VIEWPORT),
      { initialProps: { enabled: true } },
    );

    await waitFor(() => expect(result.current.size).toBe(1));

    rerender({ enabled: false });

    await waitFor(() => expect(result.current.size).toBe(0));
  });

  it("タイル取得が失敗しても（fetchWindWayPenaltiesが空オブジェクトで解決する前提で）例外を投げず空のMapに収束する", async () => {
    vi.mocked(fetchWindWayPenalties).mockResolvedValue({});

    const { result } = renderHook(() => useWindAxisPenalties(true, VIEWPORT));

    await waitFor(() => expect(fetchWindWayPenalties).toHaveBeenCalled());
    expect(result.current.size).toBe(0);
  });
});

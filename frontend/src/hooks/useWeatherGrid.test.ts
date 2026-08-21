import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useWeatherGrid } from "./useWeatherGrid";
import { getWindGrid, getWindGridDetail } from "@/services/weatherApi";
import type { WindGridPoint } from "@/types/weather";

vi.mock("@/services/weatherApi", () => ({
  getWindGrid: vi.fn(),
  getWindGridDetail: vi.fn(),
}));

function point(overrides: Partial<WindGridPoint> = {}): WindGridPoint {
  return {
    latitude: 35.68,
    longitude: 139.77,
    times: ["2026-08-20T12:00"],
    wind_speed_ms: [2.5],
    wind_direction_deg: [90],
    precipitation_mm: [0.5],
    ...overrides,
  };
}

describe("useWeatherGrid（T183: 風・延長降水予報が共有する格子点フェッチ）", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("enabled=falseの間はフェッチしない", () => {
    const { result } = renderHook(() => useWeatherGrid(false, null));
    expect(getWindGrid).not.toHaveBeenCalled();
    expect(result.current.grid).toEqual([]);
    expect(result.current.effectiveGrid).toEqual([]);
  });

  it("enabled=trueで粗い格子を取得しeffectiveGridへ反映する（詳細格子が無い間はgridそのもの）", async () => {
    vi.mocked(getWindGrid).mockResolvedValue([point()]);

    const { result } = renderHook(() => useWeatherGrid(true, null));

    await waitFor(() => expect(result.current.grid).toHaveLength(1));
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.effectiveGrid).toEqual(result.current.grid);
    expect(getWindGridDetail).not.toHaveBeenCalled();
  });

  it("取得に失敗するとerrorへメッセージを記録する", async () => {
    vi.mocked(getWindGrid).mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useWeatherGrid(true, null));

    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.loading).toBe(false);
  });

  it("ズームがWIND_DETAIL_MIN_ZOOM未満のビューポートでは詳細格子を取得しない", async () => {
    vi.mocked(getWindGrid).mockResolvedValue([point()]);

    const { result } = renderHook(() =>
      useWeatherGrid(true, { west: 139.7, south: 35.6, east: 139.8, north: 35.7, zoom: 8 })
    );

    await waitFor(() => expect(result.current.grid).toHaveLength(1));
    expect(getWindGridDetail).not.toHaveBeenCalled();
    expect(result.current.detailGrid).toEqual([]);
  });

  it("ズームがWIND_DETAIL_MIN_ZOOM以上なら詳細格子を取得し、effectiveGridはdetailGridを優先する", async () => {
    vi.mocked(getWindGrid).mockResolvedValue([point({ latitude: 35.0, longitude: 139.0 })]);
    const detailPoint = point({ latitude: 35.68, longitude: 139.77, precipitation_mm: [9.9] });
    vi.mocked(getWindGridDetail).mockResolvedValue([detailPoint]);

    const { result } = renderHook(() =>
      useWeatherGrid(true, { west: 139.7, south: 35.6, east: 139.8, north: 35.7, zoom: 13 })
    );

    await waitFor(() => expect(result.current.detailGrid).toHaveLength(1));
    expect(result.current.effectiveGrid).toEqual(result.current.detailGrid);
    expect(result.current.effectiveGrid[0].precipitation_mm).toEqual([9.9]);
  });
});

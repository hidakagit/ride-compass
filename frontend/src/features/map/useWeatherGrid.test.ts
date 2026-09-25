import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WindGridPoint } from "@/types/weather";

const api = vi.hoisted(() => ({ getWindGrid: vi.fn(), getWindGridDetail: vi.fn() }));
vi.mock("@/services/weatherApi", () => api);
// 待ち時間の間引き自体はuseDebouncedValueの持ち物。ここは値が届いた後の振る舞いを見る。
vi.mock("@/hooks/useDebouncedValue", () => ({ MAP_FETCH_DEBOUNCE_MS: 0, useDebouncedValue: <T>(value: T) => value }));

import {
  WIND_GRID_SPACING_DEG,
  windGridDetailSpacingDegForZoom,
  type MapViewport,
} from "@/features/map/layers/windLayer";

import { useWeatherGrid } from "./useWeatherGrid";

const HOURS = ["2026-09-24T09:00", "2026-09-24T10:00", "2026-09-24T11:00"];
const point = (latitude: number, longitude: number, speed = 1): WindGridPoint =>
  ({
    latitude,
    longitude,
    times: HOURS,
    wind_speed_ms: HOURS.map(() => speed),
    wind_direction_deg: HOURS.map(() => 0),
    precipitation_mm: HOURS.map(() => 0),
  }) as WindGridPoint;

const WIDE: MapViewport = { west: 139, south: 35, east: 140, north: 36, zoom: 9 };
const ZOOMED: MapViewport = { west: 139.7, south: 35.6, east: 139.72, north: 35.62, zoom: 12 };
const DETAIL_SPACING = windGridDetailSpacingDegForZoom(ZOOMED.zoom);
const FINER_SPACING = windGridDetailSpacingDegForZoom(13);

async function settle() {
  await act(async () => {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date("2026-09-24T10:30:00+09:00"));
  api.getWindGrid.mockReset().mockResolvedValue([point(35, 139)]);
  api.getWindGridDetail.mockReset().mockResolvedValue([point(35.61, 139.71)]);
});
afterEach(() => {
  vi.useRealTimers();
});

function render(enabled: boolean, viewport: MapViewport | null) {
  return renderHook(({ enabled, viewport }) => useWeatherGrid(enabled, viewport), {
    initialProps: { enabled, viewport },
  });
}

describe("useWeatherGrid（風・延長降水予報の格子）", () => {
  it("有効な間だけ粗い格子を取り、今が属する1時間より前の時刻を落とす", async () => {
    const off = render(false, WIDE);
    await settle();
    expect(api.getWindGrid).not.toHaveBeenCalled();
    off.unmount();

    const { result } = render(true, WIDE);
    await settle();
    expect(result.current.grid[0].times).toEqual(HOURS.slice(1));
    expect(result.current.effectiveGrid).toBe(result.current.grid);
    expect(result.current.effectiveGridSpacingDeg).toBe(WIND_GRID_SPACING_DEG);
    expect(result.current).toMatchObject({ loading: false, error: null, hasFetched: true });
  });

  it("取り直しで欠けた地点は、前回の値で補う", async () => {
    api.getWindGrid
      .mockResolvedValueOnce([point(35, 139), point(35.1, 139)])
      .mockResolvedValueOnce([point(35, 139, 5)]);
    const { result } = render(true, WIDE);
    await settle();
    act(() => vi.advanceTimersByTime(3 * 60 * 60 * 1000));
    await settle();
    expect(result.current.grid.map((p) => [p.latitude, p.wind_speed_ms[0]])).toEqual([
      [35, 5],
      [35.1, 1],
    ]);
  });

  it("粗い格子が取れなければ文言を出す", async () => {
    api.getWindGrid.mockRejectedValue(new Error("気象格子を取れません"));
    const { result } = render(true, WIDE);
    await settle();
    expect(result.current.error).toBe("気象格子を取れません");
  });

  it("ズームインしている間は、画面付近の詳細格子をズームに応じた間隔で取り、粗い格子の代わりに使う", async () => {
    const { result } = render(true, ZOOMED);
    await settle();
    expect(api.getWindGridDetail).toHaveBeenCalledWith(
      { minLon: 139.7, minLat: 35.6, maxLon: 139.72, maxLat: 35.62 },
      DETAIL_SPACING,
    );
    expect(result.current.detailGrid[0].times).toEqual(HOURS.slice(1));
    expect(result.current.effectiveGrid).toBe(result.current.detailGrid);
    expect(result.current.effectiveGridSpacingDeg).toBe(DETAIL_SPACING);
  });

  it("ズームアウト・無効化・詳細の取得失敗では、詳細格子を捨てて粗い格子へ戻る", async () => {
    const { result, rerender } = render(true, ZOOMED);
    await settle();
    rerender({ enabled: true, viewport: WIDE });
    await settle();
    expect(result.current.detailGrid).toEqual([]);
    expect(result.current.effectiveGridSpacingDeg).toBe(WIND_GRID_SPACING_DEG);

    rerender({ enabled: true, viewport: ZOOMED });
    await settle();
    rerender({ enabled: false, viewport: ZOOMED });
    await settle();
    expect(result.current.detailGrid).toEqual([]);

    api.getWindGridDetail.mockRejectedValueOnce(new Error("詳細を取れません"));
    rerender({ enabled: true, viewport: { ...ZOOMED, east: 139.73 } });
    await settle();
    expect(result.current.detailGrid).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it("同じ間隔のまま動かしたときは、今の範囲に入る前回の地点だけを補い、間隔が変わったら補わない", async () => {
    api.getWindGridDetail
      .mockResolvedValueOnce([point(35.61, 139.71), point(35.615, 139.715), point(35.9, 139.9)])
      .mockResolvedValueOnce([point(35.61, 139.71, 7)])
      .mockResolvedValueOnce([point(35.61, 139.71, 9)]);
    const { result, rerender } = render(true, ZOOMED);
    await settle();

    rerender({ enabled: true, viewport: { ...ZOOMED, north: 35.63 } });
    await settle();
    expect(result.current.detailGrid.map((p) => [p.latitude, p.wind_speed_ms[0]])).toEqual([
      [35.61, 7],
      [35.615, 1],
    ]);

    rerender({ enabled: true, viewport: { ...ZOOMED, zoom: 13 } });
    await settle();
    expect(api.getWindGridDetail).toHaveBeenLastCalledWith(expect.anything(), FINER_SPACING);
    expect(result.current.detailGrid.map((p) => p.wind_speed_ms[0])).toEqual([9]);
    expect(result.current.effectiveGridSpacingDeg).toBe(FINER_SPACING);
  });

  it("画面を動かした後に前の範囲の答えが届いても使わない", async () => {
    let resolveFirst!: (grid: WindGridPoint[]) => void;
    api.getWindGridDetail
      .mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
      .mockResolvedValueOnce([point(35.61, 139.71, 3)]);
    const { result, rerender } = render(true, ZOOMED);
    await settle();
    rerender({ enabled: true, viewport: { ...ZOOMED, north: 35.63 } });
    await settle();
    resolveFirst([point(35.61, 139.71, 8)]);
    await settle();
    expect(result.current.detailGrid.map((p) => p.wind_speed_ms[0])).toEqual([3]);
  });
});

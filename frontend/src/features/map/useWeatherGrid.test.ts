import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { heldReplies, inTurn, onBackend } from "@/testing/backendServer";
import type { WindGridPoint } from "@/types/weather";

// 待ち時間の間引き自体はuseDebouncedValueの持ち物。ここは値が届いた後の振る舞いを見る。
vi.mock("@/hooks/useDebouncedValue", () => ({ MAP_FETCH_DEBOUNCE_MS: 0, useDebouncedValue: <T>(value: T) => value }));

import { windGridDetailSpacingDegForZoom, type MapViewport } from "@/features/map/layers/windLayer";

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

const GRID = "/api/weather/wind-grid";
const DETAIL = "/api/weather/wind-grid-detail";

/** backendの格子の応答（時刻の列は応答に1本だけ持つ）。 */
const gridResponse = (...points: WindGridPoint[]) =>
  Response.json({ times: HOURS, points: points.map((point) => ({ ...point, times: undefined })) });
const serveGrid = (...responses: WindGridPoint[][]) =>
  onBackend("GET", GRID, inTurn(...responses.map((points) => gridResponse(...points))));
const serveDetail = (...responses: WindGridPoint[][]) =>
  onBackend("GET", DETAIL, inTurn(...responses.map((points) => gridResponse(...points))));

// 取得の結果は網を通って届くので、偽にしていない時計で届くまでの間をおく。
async function settle() {
  await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  serveGrid([point(35, 139)]);
  // 詳細格子は、問い合わせた範囲の南西の角の1点を、問い合わせた間隔を風速にして返す。
  onBackend("GET", DETAIL, ({ query }) =>
    gridResponse(point(Number(query.min_lat), Number(query.min_lon), Number(query.spacing_deg))),
  );
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
  it("有効なら粗い格子を取り、ズームしていなければ詳細格子は無い", async () => {
    const { result } = render(true, WIDE);
    await settle();
    expect(result.current.grid.map((p) => p.latitude)).toEqual([35]);
    expect(result.current).toMatchObject({ detail: null, loading: false, error: null, hasFetched: true });
  });

  it("取り直しで欠けた地点は、前回の値で補う", async () => {
    serveGrid([point(35, 139), point(35.1, 139)], [point(35, 139, 5)]);
    const { result } = render(true, WIDE);
    await settle();
    act(() => vi.advanceTimersByTime(3 * 60 * 60 * 1000));
    await settle();
    expect(result.current.grid.map((p) => [p.latitude, p.wind_speed_ms[0]])).toEqual([
      [35, 5],
      [35.1, 1],
    ]);
  });

  it("無効の間は「まだ取りに行っていない」とし、再び有効にしたら前に取った格子をすぐ出して裏で取り直す", async () => {
    serveGrid([point(35, 139)], [point(35, 139, 5)]);
    const { result, rerender } = render(true, WIDE);
    await settle();
    rerender({ enabled: false, viewport: WIDE });
    expect(result.current).toMatchObject({ grid: [], loading: false, hasFetched: false });

    rerender({ enabled: true, viewport: WIDE });
    expect(result.current.grid.map((p) => p.wind_speed_ms[0])).toEqual([1]);
    expect(result.current).toMatchObject({ loading: false, hasFetched: true });
    await settle();
    expect(result.current.grid.map((p) => p.wind_speed_ms[0])).toEqual([5]);
  });

  it("粗い格子が取れなければ文言を出す", async () => {
    onBackend("GET", GRID, () => Response.json({ detail: "気象格子を取れません" }, { status: 502 }));
    const { result } = render(true, WIDE);
    await settle();
    expect(result.current.error).toBe("気象格子を取れません");
  });

  it("ズームインしている間は、画面付近の詳細格子をズームに応じた間隔で取る", async () => {
    const { result } = render(true, ZOOMED);
    await settle();
    expect(result.current.detail?.points.map((p) => [p.latitude, p.longitude, p.wind_speed_ms[0], p.times])).toEqual([
      [35.6, 139.7, DETAIL_SPACING, HOURS],
    ]);
    expect(result.current.detail?.spacingDeg).toBe(DETAIL_SPACING);
  });

  it("ズームアウト・詳細の取得失敗では、詳細格子を捨てる", async () => {
    const { result, rerender } = render(true, ZOOMED);
    await settle();
    rerender({ enabled: true, viewport: WIDE });
    await settle();
    expect(result.current.detail).toBeNull();

    onBackend("GET", DETAIL, () => Response.json({ detail: "詳細を取れません" }, { status: 502 }));
    rerender({ enabled: true, viewport: { ...ZOOMED, east: 139.73 } });
    await settle();
    expect(result.current.detail).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("ズームしたまま配信元の更新の間隔が経つと、粗い格子と一緒に詳細格子も取り直す", async () => {
    serveGrid([point(35, 139)], [point(35, 139, 3)]);
    serveDetail([point(35.61, 139.71)], [point(35.61, 139.71, 5)]);
    const { result } = render(true, ZOOMED);
    await settle();
    act(() => vi.advanceTimersByTime(3 * 60 * 60 * 1000));
    await settle();
    expect(result.current.grid.map((p) => p.wind_speed_ms[0])).toEqual([3]);
    expect(result.current.detail?.points.map((p) => p.wind_speed_ms[0])).toEqual([5]);
  });

  it("同じ間隔のまま動かしたときは、今の範囲に入る前回の地点だけを補い、間隔が変わったら補わない", async () => {
    serveDetail(
      [point(35.61, 139.71), point(35.615, 139.715), point(35.9, 139.9)],
      [point(35.61, 139.71, 7)],
      [point(35.61, 139.71, 9)],
    );
    const { result, rerender } = render(true, ZOOMED);
    await settle();

    rerender({ enabled: true, viewport: { ...ZOOMED, north: 35.63 } });
    await settle();
    expect(result.current.detail?.points.map((p) => [p.latitude, p.wind_speed_ms[0]])).toEqual([
      [35.61, 7],
      [35.615, 1],
    ]);

    rerender({ enabled: true, viewport: { ...ZOOMED, zoom: 13 } });
    await settle();
    expect(result.current.detail?.points.map((p) => p.wind_speed_ms[0])).toEqual([9]);
    expect(result.current.detail?.spacingDeg).toBe(FINER_SPACING);
  });

  it("画面を動かして取り直している間は、前の範囲の詳細格子とその間隔を出したまま", async () => {
    const { result, rerender } = render(true, ZOOMED);
    await settle();
    const held = heldReplies();
    onBackend("GET", DETAIL, held.reply);
    rerender({ enabled: true, viewport: { ...ZOOMED, zoom: 13 } });
    await vi.waitFor(() => expect(held.arrived()).toBe(1));
    expect(result.current.detail?.points.map((p) => p.latitude)).toEqual([35.6]);
    expect(result.current.detail?.spacingDeg).toBe(DETAIL_SPACING);
  });
});

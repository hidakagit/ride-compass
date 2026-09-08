import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { dedicatedWayValuesFor, useDedicatedWayValues } from "./useDedicatedWayValues";
import type { DedicatedWayValueAxis } from "@/components/Map/axisLayers";
import { fetchDynamicWayValues } from "@/services/regionApi";
import type { MapViewport } from "@/components/Map/windLayer";

vi.mock("@/services/regionApi", async () => {
  const actual = await vi.importActual<typeof import("@/services/regionApi")>("@/services/regionApi");
  return {
    ...actual,
    fetchDynamicWayValues: vi.fn(),
  };
});

const VIEWPORT: MapViewport = { west: 139.699, south: 35.699, east: 139.701, north: 35.701, zoom: 14 };

const WIND: DedicatedWayValueAxis = {
  axisId: "wind",
  label: "風",
  needsTime: true,
  needsBearing: true,
  needsSpeed: true,
};
const GRADIENT: DedicatedWayValueAxis = {
  axisId: "gradient",
  label: "勾配",
  needsTime: false,
  needsBearing: true,
  needsSpeed: false,
};
const NO_AXES: readonly DedicatedWayValueAxis[] = [];
const WIND_ONLY: readonly DedicatedWayValueAxis[] = [WIND];
const GRADIENT_ONLY: readonly DedicatedWayValueAxis[] = [GRADIENT];
const BOTH: readonly DedicatedWayValueAxis[] = [WIND, GRADIENT];

describe("useDedicatedWayValues（専用way値配信軸のフェッチ・状態管理）", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("対象軸が0件の間はフェッチせず、空の結果を返す", () => {
    const { result } = renderHook(() => useDedicatedWayValues(NO_AXES, VIEWPORT, 0, undefined));
    expect(fetchDynamicWayValues).not.toHaveBeenCalled();
    expect(result.current.size).toBe(0);
    expect(dedicatedWayValuesFor(result.current, "wind").values.size).toBe(0);
    expect(dedicatedWayValuesFor(result.current, "wind").hasFetched).toBe(false);
  });

  it("viewportがnullの間はフェッチしない", () => {
    const { result } = renderHook(() => useDedicatedWayValues(WIND_ONLY, null, 0, undefined));
    expect(fetchDynamicWayValues).not.toHaveBeenCalled();
    expect(result.current.size).toBe(0);
  });

  it("現在のビューポートを覆うタイル分をaxis_id付きでフェッチし、統合した結果を軸ごとに返す", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: { "1": 2.5, "2": -1.0 }, error: false });
    const at = new Date("2026-08-30T09:00:00Z");

    const { result } = renderHook(() => useDedicatedWayValues(WIND_ONLY, VIEWPORT, 90, at, 20));

    await waitFor(() => expect(dedicatedWayValuesFor(result.current, "wind").values.size).toBe(2));
    const wind = dedicatedWayValuesFor(result.current, "wind");
    expect(wind.values.get(1)).toBe(2.5);
    expect(wind.values.get(2)).toBe(-1.0);
    expect(wind.error).toBe(false);
    expect(fetchDynamicWayValues).toHaveBeenCalledWith("wind", 14, 14549, 6450, 90, at, 20);
  });

  it("複数の軸を1回のフックで同時に取得する（軸ごとにフックを呼ばない）", async () => {
    vi.mocked(fetchDynamicWayValues).mockImplementation(async (axisId) => ({
      values: (axisId === "wind" ? { "1": 2.5 } : { "3": 4.5 }) as Record<string, number>,
      error: false,
    }));

    const { result } = renderHook(() => useDedicatedWayValues(BOTH, VIEWPORT, 45, undefined));

    await waitFor(() => expect(result.current.size).toBe(2));
    expect(dedicatedWayValuesFor(result.current, "wind").values.get(1)).toBe(2.5);
    expect(dedicatedWayValuesFor(result.current, "gradient").values.get(3)).toBe(4.5);
  });

  it("時刻・想定速度は、それを必要とすると宣言した軸のリクエストにだけ載る", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: {}, error: false });
    const at = new Date("2026-08-30T09:00:00Z");

    renderHook(() => useDedicatedWayValues(BOTH, VIEWPORT, 45, at, 20));

    await waitFor(() => expect(fetchDynamicWayValues).toHaveBeenCalledTimes(2));
    expect(fetchDynamicWayValues).toHaveBeenCalledWith("wind", 14, 14549, 6450, 45, at, 20);
    // 勾配はneedsTime=false・needsSpeed=falseのため、共有入力を受け取っても載せない。
    expect(fetchDynamicWayValues).toHaveBeenCalledWith("gradient", 14, 14549, 6450, 45, undefined, undefined);
  });

  it("時刻が変わっても、時刻に依存しない軸は再フェッチしない", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: { "3": 4.5 }, error: false });

    const { rerender } = renderHook(
      ({ at }: { at: Date }) => useDedicatedWayValues(BOTH, VIEWPORT, 45, at),
      { initialProps: { at: new Date("2026-08-30T09:00:00Z") } },
    );

    await waitFor(() => expect(fetchDynamicWayValues).toHaveBeenCalledTimes(2));
    vi.mocked(fetchDynamicWayValues).mockClear();

    rerender({ at: new Date("2026-08-30T12:00:00Z") });

    await waitFor(() => expect(fetchDynamicWayValues).toHaveBeenCalledTimes(1));
    expect(fetchDynamicWayValues).toHaveBeenCalledWith("wind", 14, 14549, 6450, 45, expect.any(Date), undefined);
  });

  it("byTileにタイルごとの生応答を保持する（gridFillのタイル単位集計向け）", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: { "1": 2.5 }, error: false });

    const { result } = renderHook(() => useDedicatedWayValues(GRADIENT_ONLY, VIEWPORT, 0, undefined));

    await waitFor(() => expect(dedicatedWayValuesFor(result.current, "gradient").byTile.length).toBe(1));
    const byTile = dedicatedWayValuesFor(result.current, "gradient").byTile;
    expect(byTile[0].tile).toEqual({ z: 14, x: 14549, y: 6450 });
    expect(byTile[0].values).toEqual({ "1": 2.5 });
  });

  it("対象軸から外すと、その軸の結果を捨てる", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: { "1": 2.5 }, error: false });

    const { result, rerender } = renderHook(
      ({ axes }: { axes: readonly DedicatedWayValueAxis[] }) => useDedicatedWayValues(axes, VIEWPORT, 0, undefined),
      { initialProps: { axes: WIND_ONLY } },
    );

    await waitFor(() => expect(dedicatedWayValuesFor(result.current, "wind").values.size).toBe(1));

    rerender({ axes: NO_AXES });

    await waitFor(() => expect(dedicatedWayValuesFor(result.current, "wind").values.size).toBe(0));
    expect(dedicatedWayValuesFor(result.current, "wind").loading).toBe(false);
  });

  it("フェッチ中はloading=trueになり、応答が届くとfalseに戻る", async () => {
    let resolveFetch!: (value: { values: Record<string, number>; error: boolean }) => void;
    vi.mocked(fetchDynamicWayValues).mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const { result } = renderHook(() => useDedicatedWayValues(WIND_ONLY, VIEWPORT, 0, undefined));

    await waitFor(() => expect(dedicatedWayValuesFor(result.current, "wind").loading).toBe(true));
    expect(dedicatedWayValuesFor(result.current, "wind").values.size).toBe(0);

    resolveFetch({ values: { "1": 2.5 }, error: false });

    await waitFor(() => expect(dedicatedWayValuesFor(result.current, "wind").loading).toBe(false));
    expect(dedicatedWayValuesFor(result.current, "wind").values.get(1)).toBe(2.5);
  });

  it("タイル取得が本当に空（backendが正常応答でerror:falseの空values）なら、例外を投げず空の結果に収束しerrorはfalseのまま", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: {}, error: false });

    const { result } = renderHook(() => useDedicatedWayValues(WIND_ONLY, VIEWPORT, 0, undefined));

    await waitFor(() => expect(fetchDynamicWayValues).toHaveBeenCalled());
    await waitFor(() => expect(dedicatedWayValuesFor(result.current, "wind").hasFetched).toBe(true));
    expect(dedicatedWayValuesFor(result.current, "wind").values.size).toBe(0);
    expect(dedicatedWayValuesFor(result.current, "wind").error).toBe(false);
  });

  it("いずれかのタイルの取得が失敗（error:true）したら、その軸の結果のerrorをtrueにする", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: {}, error: true });

    const { result } = renderHook(() => useDedicatedWayValues(WIND_ONLY, VIEWPORT, 0, undefined));

    // 初期状態のloading（空の結果）もfalseのため、loading===falseだけを待つと
    // フェッチ完了前に条件が満たされてしまう。フェッチが呼ばれたことをまず待つ。
    await waitFor(() => expect(fetchDynamicWayValues).toHaveBeenCalled());
    await waitFor(() => expect(dedicatedWayValuesFor(result.current, "wind").error).toBe(true));
    expect(dedicatedWayValuesFor(result.current, "wind").values.size).toBe(0);
  });
});

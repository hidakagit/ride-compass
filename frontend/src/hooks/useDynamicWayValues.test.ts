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
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe(false);
  });

  it("viewportがnullの間はフェッチしない", () => {
    const { result } = renderHook(() => useDynamicWayValues("wind", true, null, 0, undefined));
    expect(fetchDynamicWayValues).not.toHaveBeenCalled();
    expect(result.current.values.size).toBe(0);
  });

  it("enabled=trueで、現在のビューポートを覆うタイル分をmaterial_id付きでフェッチし統合した結果を返す", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: { "1": 2.5, "2": -1.0 }, error: false });
    const at = new Date("2026-08-30T09:00:00Z");

    const { result } = renderHook(() => useDynamicWayValues("wind", true, VIEWPORT, 90, at));

    await waitFor(() => expect(result.current.values.size).toBe(2));
    expect(result.current.values.get(1)).toBe(2.5);
    expect(result.current.values.get(2)).toBe(-1.0);
    expect(result.current.error).toBe(false);
    expect(fetchDynamicWayValues).toHaveBeenCalledWith("wind", 14, 14549, 6450, 90, at, undefined);
  });

  it("material_idが異なれば別々の値としてフェッチする（gradientの例）", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: { "3": 4.5 }, error: false });

    const { result } = renderHook(() => useDynamicWayValues("gradient", true, VIEWPORT, 45, undefined));

    await waitFor(() => expect(result.current.values.size).toBe(1));
    expect(fetchDynamicWayValues).toHaveBeenCalledWith("gradient", 14, 14549, 6450, 45, undefined, undefined);
  });

  it("byTileにタイルごとの生応答を保持する（gridFillのタイル単位集計向け）", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: { "1": 2.5 }, error: false });

    const { result } = renderHook(() => useDynamicWayValues("gradient", true, VIEWPORT, 0, undefined));

    await waitFor(() => expect(result.current.byTile.length).toBe(1));
    expect(result.current.byTile[0].tile).toEqual({ z: 14, x: 14549, y: 6450 });
    expect(result.current.byTile[0].values).toEqual({ "1": 2.5 });
  });

  it("OFFへ切り替えると結果を空へ戻す", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: { "1": 2.5 }, error: false });

    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useDynamicWayValues("wind", enabled, VIEWPORT, 0, undefined),
      { initialProps: { enabled: true } },
    );

    await waitFor(() => expect(result.current.values.size).toBe(1));

    rerender({ enabled: false });

    await waitFor(() => expect(result.current.values.size).toBe(0));
    expect(result.current.loading).toBe(false);
  });

  it("フェッチ中はloading=trueになり、応答が届くとfalseに戻る（改善計画T607）", async () => {
    let resolveFetch!: (value: { values: Record<string, number>; error: boolean }) => void;
    vi.mocked(fetchDynamicWayValues).mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const { result } = renderHook(() => useDynamicWayValues("wind", true, VIEWPORT, 0, undefined));

    await waitFor(() => expect(result.current.loading).toBe(true));
    expect(result.current.values.size).toBe(0);

    resolveFetch({ values: { "1": 2.5 }, error: false });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.values.get(1)).toBe(2.5);
  });

  it("タイル取得が本当に空（backendが正常応答でerror:falseの空values）なら、例外を投げず空の結果に収束しerrorはfalseのまま", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: {}, error: false });

    const { result } = renderHook(() => useDynamicWayValues("wind", true, VIEWPORT, 0, undefined));

    await waitFor(() => expect(fetchDynamicWayValues).toHaveBeenCalled());
    expect(result.current.values.size).toBe(0);
    expect(result.current.error).toBe(false);
  });

  it("いずれかのタイルの取得が失敗（error:true）したら、結果全体のerrorをtrueにする", async () => {
    vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: {}, error: true });

    const { result } = renderHook(() => useDynamicWayValues("wind", true, VIEWPORT, 0, undefined));

    // 初期状態のloading（EMPTY_RESULT）もfalseのため、loading===falseだけを待つと
    // フェッチ完了前に条件が満たされてしまう（本テストで実際に踏んだ罠）。フェッチが
    // 呼ばれたことをまず待ってから、errorの反映を待つ。
    await waitFor(() => expect(fetchDynamicWayValues).toHaveBeenCalled());
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.values.size).toBe(0);
  });
});

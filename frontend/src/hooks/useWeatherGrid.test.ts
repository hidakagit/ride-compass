import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useWeatherGrid } from "./useWeatherGrid";
import { getWindGrid, getWindGridDetail } from "@/services/weatherApi";
import { WIND_GRID_SPACING_DEG, type MapViewport } from "@/components/Map/windLayer";
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
    expect(result.current.effectiveGridSpacingDeg).toBe(WIND_GRID_SPACING_DEG);
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

  describe("ズーム依存のdetail格子間隔（T185、実機フィードバック「拡大率が大きいとgridFillの格子がゴワゴワして気になる」）", () => {
    it("ズーム13ではspacingDeg=0.01でリクエストし、effectiveGridSpacingDegへ反映する", async () => {
      vi.mocked(getWindGrid).mockResolvedValue([point({ latitude: 35.0, longitude: 139.0 })]);
      vi.mocked(getWindGridDetail).mockResolvedValue([point()]);

      const { result } = renderHook(() =>
        useWeatherGrid(true, { west: 139.7, south: 35.6, east: 139.8, north: 35.7, zoom: 13 })
      );

      await waitFor(() => expect(result.current.detailGrid).toHaveLength(1));
      expect(getWindGridDetail).toHaveBeenCalledWith(expect.anything(), 0.01);
      expect(result.current.effectiveGridSpacingDeg).toBe(0.01);
    });

    it("ズーム19ではspacingDeg=0.0025でリクエストする（さらに細かい段階）", async () => {
      vi.mocked(getWindGrid).mockResolvedValue([point({ latitude: 35.0, longitude: 139.0 })]);
      vi.mocked(getWindGridDetail).mockResolvedValue([point()]);

      const { result } = renderHook(() =>
        useWeatherGrid(true, { west: 139.7, south: 35.6, east: 139.8, north: 35.7, zoom: 19 })
      );

      await waitFor(() => expect(result.current.detailGrid).toHaveLength(1));
      expect(getWindGridDetail).toHaveBeenCalledWith(expect.anything(), 0.0025);
      expect(result.current.effectiveGridSpacingDeg).toBe(0.0025);
    });
  });

  describe("詳細格子の失敗フォールバック・間隔変更時のリセット（改善計画T331）", () => {
    it("詳細格子の取得に失敗すると、エラー表示はせずdetailGridを空にして粗い格子へ静かにフォールバックする", async () => {
      vi.mocked(getWindGrid).mockResolvedValue([point({ latitude: 35.0, longitude: 139.0 })]);
      vi.mocked(getWindGridDetail).mockResolvedValueOnce([point()]);

      const { result, rerender } = renderHook(
        ({ viewport }: { viewport: MapViewport }) => useWeatherGrid(true, viewport),
        { initialProps: { viewport: { west: 139.7, south: 35.6, east: 139.8, north: 35.7, zoom: 13 } } }
      );

      // まず正常系: 詳細格子が1件取得できることを確認してから、続く再取得を失敗させる。
      await waitFor(() => expect(result.current.detailGrid).toHaveLength(1));
      expect(result.current.effectiveGrid).toEqual(result.current.detailGrid);

      vi.mocked(getWindGridDetail).mockRejectedValueOnce(new Error("open-meteo 429"));
      rerender({ viewport: { west: 139.71, south: 35.61, east: 139.81, north: 35.71, zoom: 13 } });

      await waitFor(() => expect(result.current.detailGrid).toHaveLength(0));
      // 補助的な機能のため、詳細格子側の失敗はerrorへ反映されず、effectiveGridは粗い格子へ
      // 静かにフォールバックする（フックのUseWeatherGridResult.errorのドキュメント参照）。
      expect(result.current.error).toBeNull();
      expect(result.current.effectiveGrid).toEqual(result.current.grid);
      expect(result.current.effectiveGridSpacingDeg).toBe(WIND_GRID_SPACING_DEG);
    });

    it("ズームをまたいで格子間隔が変わると、直前の間隔の詳細格子点を穴埋め用に持ち越さない", async () => {
      vi.mocked(getWindGrid).mockResolvedValue([point({ latitude: 35.0, longitude: 139.0 })]);
      // ビューポート中心と同じ座標にして、ズーム13→19どちらのclampWindDetailBboxでも
      // 確実にbbox内へ収まるようにする（間隔が変わってもbbox内に「居続ける」点でないと、
      // 「間隔が変わったから捨てた」のか「bbox外に出たから捨てた」のか区別できないため）。
      const centerPoint = point({ latitude: 35.65, longitude: 139.725 });
      vi.mocked(getWindGridDetail).mockResolvedValueOnce([centerPoint]);

      const { result, rerender } = renderHook(
        ({ viewport }: { viewport: MapViewport }) => useWeatherGrid(true, viewport),
        {
          initialProps: {
            viewport: { west: 139.6, south: 35.55, east: 139.85, north: 35.75, zoom: 13 },
          },
        }
      );

      await waitFor(() => expect(result.current.detailGrid).toHaveLength(1));
      expect(result.current.effectiveGridSpacingDeg).toBe(0.01);

      // 同じビューポート範囲のままズームだけを19へ上げる（spacingDeg 0.01→0.0025）。
      // 今回のfetchは空配列（一時的に取得できなかった状態）を返す——間隔が変わらなければ
      // mergeWindGridKeepingStaleがcenterPointを穴埋め用に持ち越しdetailGridは1件のままの
      // はずだが、間隔が変わった場合は持ち越し自体をリセットする実装（useWeatherGrid.ts:
      // spacingChanged判定）のため、0件になるべき（0件になるとeffectiveGridSpacingDegは
      // detailGridが空の間の既定フォールバックであるWIND_GRID_SPACING_DEGへ戻る。これは
      // 別テスト「ズームが...未満のビューポートでは詳細格子を取得しない」で確認済みの
      // 既存の意図した挙動なので、ここではリクエストに使われたspacingDeg自体
      // （新しい間隔0.0025でリクエストされたこと）とdetailGridが0件になったことを見る）。
      vi.mocked(getWindGridDetail).mockResolvedValueOnce([]);
      rerender({
        viewport: { west: 139.6, south: 35.55, east: 139.85, north: 35.75, zoom: 19 },
      });

      await waitFor(() => expect(getWindGridDetail).toHaveBeenLastCalledWith(expect.anything(), 0.0025));
      await waitFor(() => expect(result.current.detailGrid).toHaveLength(0));
      expect(result.current.effectiveGridSpacingDeg).toBe(WIND_GRID_SPACING_DEG);
    });
  });
});

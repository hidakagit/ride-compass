import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDynamicWeatherLayers } from "./useDynamicWeatherLayers";
import { fetchNowcastFrames, fetchRasrfFrames } from "@/components/Map/precipitationNowcast";
import { fetchThunderNowcastFrames } from "@/components/Map/thunderNowcast";
import { fetchLidenFrames, fetchLidenGeojson } from "@/components/Map/lidenLayer";
import { fetchCurrentRiskFrames, fetchLinearRainbandFrames } from "@/components/Map/riskMap";
import { useWeatherGrid } from "@/hooks/useWeatherGrid";

vi.mock("@/components/Map/precipitationNowcast", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/Map/precipitationNowcast")>()),
  fetchNowcastFrames: vi.fn(),
  fetchRasrfFrames: vi.fn(),
}));
vi.mock("@/components/Map/thunderNowcast", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/Map/thunderNowcast")>()),
  fetchThunderNowcastFrames: vi.fn(),
}));
vi.mock("@/components/Map/lidenLayer", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/Map/lidenLayer")>()),
  fetchLidenFrames: vi.fn(),
  fetchLidenGeojson: vi.fn(),
}));
vi.mock("@/components/Map/riskMap", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/Map/riskMap")>()),
  fetchCurrentRiskFrames: vi.fn(),
  fetchLinearRainbandFrames: vi.fn(),
}));
vi.mock("@/hooks/useWeatherGrid", () => ({
  useWeatherGrid: vi.fn(),
}));

const EMPTY_CURRENT_RISK_FRAMES = { land: [], heavyRain: [], inundation: [], flood: [] };

const BASE_OPTIONS = {
  showWindVector: false,
  showPrecipitationNowcast: false,
  showDisaster: false,
  mapViewport: null,
};

describe("useDynamicWeatherLayers（改善計画T425: キキクル・線状降水帯予測マップのエラー可視化）", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  function stubHappyPath() {
    vi.mocked(fetchNowcastFrames).mockResolvedValue([]);
    vi.mocked(fetchRasrfFrames).mockResolvedValue([]);
    vi.mocked(fetchThunderNowcastFrames).mockResolvedValue([]);
    vi.mocked(fetchLidenFrames).mockResolvedValue([]);
    vi.mocked(fetchCurrentRiskFrames).mockResolvedValue(EMPTY_CURRENT_RISK_FRAMES);
    vi.mocked(fetchLinearRainbandFrames).mockResolvedValue([]);
    vi.mocked(useWeatherGrid).mockReturnValue({
      grid: [],
      detailGrid: [],
      effectiveGrid: [],
      effectiveGridSpacingDeg: 0.05,
      loading: false,
      error: null,
    });
  }

  it("全フェッチ成功時はどのレイヤーもerrorにならない（フレーム0件のためempty）", async () => {
    stubHappyPath();

    const { result } = renderHook(() =>
      useDynamicWeatherLayers({ ...BASE_OPTIONS, showPrecipitationNowcast: true, showDisaster: true })
    );

    await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
    await waitFor(() => expect(fetchLinearRainbandFrames).toHaveBeenCalled());
    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).toBe("empty"));
    expect(result.current.dynamicWeatherDataStatus.disaster).toBe("empty");
  });

  it("キキクル（現在のリスク分布）の取得失敗が、災害チップ1つ分のdynamicWeatherDataStatusへ反映される", async () => {
    stubHappyPath();
    vi.mocked(fetchCurrentRiskFrames).mockRejectedValue(new Error("kikkuru boom"));

    const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showDisaster: true }));

    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error"));
  });

  it("線状降水帯予測マップの取得失敗が、降水チップON時にdynamicWeatherDataStatus.precipitationNowcastへ反映される", async () => {
    stubHappyPath();
    vi.mocked(fetchLinearRainbandFrames).mockRejectedValue(new Error("linear rainband boom"));

    const { result } = renderHook(() =>
      useDynamicWeatherLayers({ ...BASE_OPTIONS, showPrecipitationNowcast: true })
    );

    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).toBe("error"));
  });

  it("線状降水帯予測マップの取得失敗は、降水チップOFF時はフェッチ自体走らずdynamicWeatherDataStatusに反映されない", async () => {
    stubHappyPath();

    renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showDisaster: true }));

    await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
    expect(fetchLinearRainbandFrames).not.toHaveBeenCalled();
  });

  describe("dynamicWeatherDataStatus（改善計画T608: MapLibreのソースイベントを経由しない統一IF）", () => {
    it("フェッチが解決するまでloading、解決後はpayloadの有無に応じてempty/正常になる", async () => {
      let resolveFetch!: (frames: Awaited<ReturnType<typeof fetchThunderNowcastFrames>>) => void;
      vi.mocked(fetchThunderNowcastFrames).mockReturnValue(
        new Promise((resolve) => {
          resolveFetch = resolve;
        })
      );

      const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showDisaster: true }));

      await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("loading"));

      resolveFetch([]);

      await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("empty"));
    });

    it("windVectorも同じ仕組みで判定する（風の格子点フェッチがエラーならerror）", async () => {
      stubHappyPath();
      vi.mocked(useWeatherGrid).mockReturnValue({
        grid: [],
        detailGrid: [],
        effectiveGrid: [],
        effectiveGridSpacingDeg: 0.05,
        loading: false,
        error: "wind grid boom",
      });

      const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showWindVector: true }));

      await waitFor(() => expect(result.current.dynamicWeatherDataStatus.windVector).toBe("error"));
    });

    it("OFF中のレイヤーにも値は計算されるが（表示側がon/layerVisibilityで抑制するため）害はない", () => {
      stubHappyPath();

      const { result } = renderHook(() => useDynamicWeatherLayers(BASE_OPTIONS));

      expect(result.current.dynamicWeatherDataStatus.disaster).toBe("empty");
    });
  });

  describe("災害グループ（雷・竜巻・落雷・キキクル4種を1チップへ統合）", () => {
    it("OFFの間は3本のフェッチ（キキクル・雷竜巻・落雷）いずれも走らない", () => {
      stubHappyPath();

      renderHook(() => useDynamicWeatherLayers(BASE_OPTIONS));

      expect(fetchCurrentRiskFrames).not.toHaveBeenCalled();
      expect(fetchThunderNowcastFrames).not.toHaveBeenCalled();
      expect(fetchLidenFrames).not.toHaveBeenCalled();
    });

    it("ONにすると3本のフェッチがまとめて走る", async () => {
      stubHappyPath();

      renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showDisaster: true }));

      await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
      expect(fetchThunderNowcastFrames).toHaveBeenCalled();
      expect(fetchLidenFrames).toHaveBeenCalled();
    });

    it("7ソースすべてが1つのチップのON/OFFに連動し、payloadはデータのある要素にだけ載る", async () => {
      stubHappyPath();
      const frame = [{ time: new Date(), ref: { basetime: "0", validtime: "0", member: "" } }];
      vi.mocked(fetchCurrentRiskFrames).mockResolvedValue({ land: frame, heavyRain: frame, inundation: [], flood: [] });

      const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showDisaster: true }));

      await waitFor(() => expect(result.current.dynamicWeather.disaster?.landslide?.payload).toBeDefined());
      const disaster = result.current.dynamicWeather.disaster;
      for (const source of ["heavyRain", "landslide", "inundation", "thunder", "tornado", "flood", "liden"]) {
        expect(disaster?.[source]?.visible).toBe(true);
      }
      // フレームを返さなかった要素はpayload未確定のまま（visibleとpayloadの両方が
      // 揃わない限りMapView側は描画しない）。
      expect(disaster?.heavyRain?.payload).toBeDefined();
      expect(disaster?.inundation?.payload).toBeUndefined();
      expect(disaster?.flood?.payload).toBeUndefined();
    });
  });

  describe("雷放電位置データ（liden、災害グループのソースの1つ）", () => {
    it("時刻一覧の取得失敗がdynamicWeatherDataStatus.disasterへ反映される", async () => {
      stubHappyPath();
      vi.mocked(fetchLidenFrames).mockRejectedValue(new Error("liden boom"));

      const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showDisaster: true }));

      await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error"));
    });

    it("選択中フレームのGeoJSONが取得できるとdisasterグループのlidenソースのpayloadへ反映される", async () => {
      stubHappyPath();
      // dynamicLayerTargetTimeの初期値は実時刻（new Date()）のため、frameIndexForTimeの
      // 許容誤差（1秒）内に入るよう、フレームのvalidtimeもテスト実行時点の実時刻から
      // JMAタイムスタンプ形式（YYYYMMDDHHmmss、UTC）で組み立てる。
      const now = new Date();
      const pad = (n: number) => String(n).padStart(2, "0");
      const validtime =
        `${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}` +
        `${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}${pad(now.getUTCSeconds())}`;
      vi.mocked(fetchLidenFrames).mockResolvedValue([{ basetime: validtime, validtime, isForecast: false }]);
      const geojson = { type: "FeatureCollection" as const, features: [] };
      vi.mocked(fetchLidenGeojson).mockResolvedValue(geojson);

      const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showDisaster: true }));

      await waitFor(() =>
        expect(result.current.dynamicWeather.disaster?.liden?.payload).toEqual({ kind: "gridMark", geojson })
      );
    });
  });
});

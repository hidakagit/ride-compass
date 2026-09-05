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
  showThunderNowcast: false,
  showTornadoNowcast: false,
  showLiden: false,
  showLandslideRisk: false,
  showHeavyRainRisk: false,
  showInundationRisk: false,
  showFloodRisk: false,
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
      useDynamicWeatherLayers({ ...BASE_OPTIONS, showPrecipitationNowcast: true, showLandslideRisk: true })
    );

    await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
    await waitFor(() => expect(fetchLinearRainbandFrames).toHaveBeenCalled());
    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).toBe("empty"));
    expect(result.current.dynamicWeatherDataStatus.landslideRisk).toBe("empty");
  });

  it("キキクル（現在のリスク分布）の取得失敗が、キキクル4種すべてのdynamicWeatherDataStatusへ反映される", async () => {
    stubHappyPath();
    vi.mocked(fetchCurrentRiskFrames).mockRejectedValue(new Error("kikkuru boom"));

    const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showLandslideRisk: true }));

    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.landslideRisk).toBe("error"));
    expect(result.current.dynamicWeatherDataStatus.heavyRainRisk).toBe("error");
    expect(result.current.dynamicWeatherDataStatus.inundationRisk).toBe("error");
    expect(result.current.dynamicWeatherDataStatus.floodRisk).toBe("error");
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

    renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showLandslideRisk: true }));

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

      const { result } = renderHook(() =>
        useDynamicWeatherLayers({ ...BASE_OPTIONS, showThunderNowcast: true })
      );

      await waitFor(() => expect(result.current.dynamicWeatherDataStatus.thunderNowcast).toBe("loading"));

      resolveFetch([]);

      await waitFor(() => expect(result.current.dynamicWeatherDataStatus.thunderNowcast).toBe("empty"));
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

      expect(result.current.dynamicWeatherDataStatus.thunderNowcast).toBe("empty");
    });
  });

  describe("キキクル4種（改善計画T606: 地図上チップ化）", () => {
    it("4種すべてOFFの間はフェッチ自体走らない", () => {
      stubHappyPath();

      renderHook(() => useDynamicWeatherLayers(BASE_OPTIONS));

      expect(fetchCurrentRiskFrames).not.toHaveBeenCalled();
    });

    it("いずれか1つでもONならフェッチする（4種で1本のtargetTimes.jsonを共有）", async () => {
      stubHappyPath();

      renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showFloodRisk: true }));

      await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
    });

    it("showXxx=trueの要素だけvisible: trueでpayloadを持ち、showXxx=falseの要素はvisible: falseのまま", async () => {
      stubHappyPath();
      const frame = [{ time: new Date(), ref: { basetime: "0", validtime: "0", member: "" } }];
      vi.mocked(fetchCurrentRiskFrames).mockResolvedValue({ land: frame, heavyRain: frame, inundation: [], flood: [] });

      const { result } = renderHook(() =>
        useDynamicWeatherLayers({ ...BASE_OPTIONS, showLandslideRisk: true, showHeavyRainRisk: false })
      );

      await waitFor(() => expect(result.current.dynamicWeather.landslideRisk?.main?.payload).toBeDefined());
      expect(result.current.dynamicWeather.landslideRisk?.main?.visible).toBe(true);
      expect(result.current.dynamicWeather.heavyRainRisk?.main?.visible).toBe(false);
    });
  });

  describe("雷放電位置データ（liden、改善計画T541）", () => {
    it("showLiden=falseの間はフェッチ自体走らない", () => {
      stubHappyPath();

      renderHook(() => useDynamicWeatherLayers(BASE_OPTIONS));

      expect(fetchLidenFrames).not.toHaveBeenCalled();
    });

    it("時刻一覧の取得失敗がdynamicWeatherDataStatus.lidenへ反映される", async () => {
      stubHappyPath();
      vi.mocked(fetchLidenFrames).mockRejectedValue(new Error("liden boom"));

      const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showLiden: true }));

      await waitFor(() => expect(result.current.dynamicWeatherDataStatus.liden).toBe("error"));
    });

    it("選択中フレームのGeoJSONが取得できるとdynamicWeather.lidenのpayloadへ反映される", async () => {
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

      const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showLiden: true }));

      await waitFor(() => expect(result.current.dynamicWeather.liden?.main?.payload).toEqual({ kind: "gridMark", geojson }));
    });
  });
});

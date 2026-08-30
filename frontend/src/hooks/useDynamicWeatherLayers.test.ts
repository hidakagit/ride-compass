import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDynamicWeatherLayers } from "./useDynamicWeatherLayers";
import { fetchNowcastFrames, fetchRasrfFrames } from "@/components/Map/precipitationNowcast";
import { fetchThunderNowcastFrames } from "@/components/Map/thunderNowcast";
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
vi.mock("@/components/Map/riskMap", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/Map/riskMap")>()),
  fetchCurrentRiskFrames: vi.fn(),
  fetchLinearRainbandFrames: vi.fn(),
}));
vi.mock("@/hooks/useWeatherGrid", () => ({
  useWeatherGrid: vi.fn(),
}));

const EMPTY_CURRENT_RISK_FRAMES = { land: [], heavyRain: [], inundation: [] };

const BASE_OPTIONS = {
  showWindVector: false,
  windBearingDeg: 0,
  showWindPenaltyFill: false,
  showPrecipitationNowcast: false,
  showThunderNowcast: false,
  showTornadoNowcast: false,
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

  it("全フェッチ成功時はdynamicLayerErrorがnullのまま（キキクル・線状降水帯予測マップは常時/降水チップ連動でフェッチされる）", async () => {
    stubHappyPath();

    const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showPrecipitationNowcast: true }));

    await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
    await waitFor(() => expect(fetchLinearRainbandFrames).toHaveBeenCalled());
    expect(result.current.dynamicLayerError).toBeNull();
  });

  it("キキクル（現在のリスク分布）の取得失敗がdynamicLayerErrorへ反映される（show*ガード無しの常時マウント）", async () => {
    stubHappyPath();
    vi.mocked(fetchCurrentRiskFrames).mockRejectedValue(new Error("kikkuru boom"));

    const { result } = renderHook(() => useDynamicWeatherLayers(BASE_OPTIONS));

    await waitFor(() => expect(result.current.dynamicLayerError).toBe("kikkuru boom"));
  });

  it("線状降水帯予測マップの取得失敗が、降水チップON時にdynamicLayerErrorへ反映される", async () => {
    stubHappyPath();
    vi.mocked(fetchLinearRainbandFrames).mockRejectedValue(new Error("linear rainband boom"));

    const { result } = renderHook(() =>
      useDynamicWeatherLayers({ ...BASE_OPTIONS, showPrecipitationNowcast: true })
    );

    await waitFor(() => expect(result.current.dynamicLayerError).toBe("linear rainband boom"));
  });

  it("線状降水帯予測マップの取得失敗は、降水チップOFF時はフェッチ自体走らずdynamicLayerErrorに反映されない", async () => {
    stubHappyPath();

    renderHook(() => useDynamicWeatherLayers(BASE_OPTIONS));

    await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
    expect(fetchLinearRainbandFrames).not.toHaveBeenCalled();
  });
});

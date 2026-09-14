import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDynamicWeatherLayers } from "./useDynamicWeatherLayers";
import { fetchNowcastFrames, fetchRasrfFrames, type NowcastFrame } from "@/components/Map/precipitationNowcast";
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
  hiddenDisasterSources: [],
  mapViewport: null,
};

const FIVE_MIN_MS = 5 * 60 * 1000;

/** Date → 気象庁のタイムスタンプ形式（YYYYMMDDHHmmss、UTC）。 */
function jmaTimestamp(time: Date): string {
  return time.toISOString().replace(/[-:T]/g, "").slice(0, 14);
}

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
    hasFetched: true,
    error: null,
  });
}

describe("useDynamicWeatherLayers（改善計画T425: キキクル・線状降水帯予測マップのエラー可視化）", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });


  it("全フェッチ成功時はどのレイヤーもerrorにならない（フレーム0件のためempty）", async () => {
    stubHappyPath();

    const { result } = renderHook(() =>
      useDynamicWeatherLayers({ ...BASE_OPTIONS, showPrecipitationNowcast: true, showDisaster: true })
    );

    await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
    await waitFor(() => expect(fetchLinearRainbandFrames).toHaveBeenCalled());
    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).toBe("empty"));
    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("empty"));
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
        hasFetched: true,
        error: "wind grid boom",
      });

      const { result } = renderHook(() => useDynamicWeatherLayers({ ...BASE_OPTIONS, showWindVector: true }));

      await waitFor(() => expect(result.current.dynamicWeatherDataStatus.windVector).toBe("error"));
    });

    it("OFF中のレイヤーは取得を試みていないため状態を持たない（emptyと断定しない）", () => {
      // OFFの間はフェッチ自体が走らない（enabled: false）。ここをemptyにすると
      // 「この範囲に表示できるデータがありません」と読めてしまい、配線ミスで
      // フェッチが走っていない状態と区別が付かなくなる。
      stubHappyPath();

      const { result } = renderHook(() => useDynamicWeatherLayers(BASE_OPTIONS));

      expect(result.current.dynamicWeatherDataStatus.disaster).toBeUndefined();
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

  describe("災害グループの要素トグル（▶パネルの「表示する情報」）", () => {
    it("非表示に選ばれた要素はvisible: falseになり、他の要素は表示のまま残る", async () => {
      stubHappyPath();

      const { result } = renderHook(() =>
        useDynamicWeatherLayers({
          ...BASE_OPTIONS,
          showDisaster: true,
          hiddenDisasterSources: ["thunder", "tornado", "liden"],
        })
      );

      await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
      const disaster = result.current.dynamicWeather.disaster;
      expect(disaster?.thunder?.visible).toBe(false);
      expect(disaster?.tornado?.visible).toBe(false);
      expect(disaster?.liden?.visible).toBe(false);
      expect(disaster?.heavyRain?.visible).toBe(true);
      expect(disaster?.flood?.visible).toBe(true);
    });

    it("1本のtargetTimes.jsonを共有する要素がすべて非表示なら、そのフェッチ自体を行わない", async () => {
      stubHappyPath();

      renderHook(() =>
        useDynamicWeatherLayers({
          ...BASE_OPTIONS,
          showDisaster: true,
          hiddenDisasterSources: ["heavyRain", "landslide", "inundation", "flood", "liden"],
        })
      );

      // 雷・竜巻だけが表示中なので、雷竜巻のフレーム取得だけが走る。
      await waitFor(() => expect(fetchThunderNowcastFrames).toHaveBeenCalled());
      expect(fetchCurrentRiskFrames).not.toHaveBeenCalled();
      expect(fetchLidenFrames).not.toHaveBeenCalled();
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
      // 見るのはGeoJSONがpayloadへ届く配線であって時刻範囲の判定ではないため、フレームを
      // 共有時刻そのもの（5分へ丸めた現在時刻）に置く。気象庁のlidenのvalidtimeは実際に
      // 5分刻みのため、任意の秒を持つ時刻はそもそも実データに存在しない。
      const validtime = jmaTimestamp(new Date(Math.floor(Date.now() / FIVE_MIN_MS) * FIVE_MIN_MS));
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

describe("共有時刻の「今」への追従（改善計画T859）", () => {
  const STEP_MS = FIVE_MIN_MS;
  // 5分境界ちょうどではない時刻から始め、丸めが効いていることも同時に見る。
  const T0 = Date.UTC(2026, 8, 15, 10, 2, 30);

  /** 実況1件＋60分先までの予測。実況の時刻は呼ばれた瞬間の「今」を5分へ丸めたもの
   * ——本物の気象庁が5分毎に実況を更新し、trimToCurrentAndFutureがフレーム列の先頭を
   * そこへ切り詰めるのを再現する。 */
  function nowcastFramesForNow(): NowcastFrame[] {
    const observed = Math.floor(Date.now() / STEP_MS) * STEP_MS;
    const frames: NowcastFrame[] = [
      { basetime: jmaTimestamp(new Date(observed)), validtime: jmaTimestamp(new Date(observed)), isForecast: false },
    ];
    for (let offset = STEP_MS; offset <= 60 * 60 * 1000; offset += STEP_MS) {
      frames.push({ basetime: jmaTimestamp(new Date(observed)), validtime: jmaTimestamp(new Date(observed + offset)), isForecast: true });
    }
    return frames;
  }

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("時間が経つと共有時刻も進む（進まないと降水が範囲外になり黙って消える）", async () => {
    stubHappyPath();
    vi.mocked(fetchNowcastFrames).mockImplementation(async () => nowcastFramesForNow());

    const { result } = renderHook(() =>
      useDynamicWeatherLayers({ ...BASE_OPTIONS, showPrecipitationNowcast: true })
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.dynamicWeather.precipitationNowcast.main.payload).toBeDefined();

    // 実況が2回更新される長さ。共有時刻が止まっていればここで範囲外へ落ちる。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11 * 60 * 1000);
    });

    expect(result.current.dynamicWeather.precipitationNowcast.main.payload).toBeDefined();
    expect(result.current.dynamicLayerTargetTime.getTime()).toBe(
      Math.floor((T0 + 11 * 60 * 1000) / STEP_MS) * STEP_MS
    );
  });

  it("利用者が選んだ出発時刻は、時間が経っても勝手に動かない", async () => {
    stubHappyPath();
    const chosen = new Date(T0 + 30 * 60 * 1000);

    const { result } = renderHook(() => useDynamicWeatherLayers(BASE_OPTIONS));

    act(() => result.current.setDynamicLayerTargetTime(chosen));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11 * 60 * 1000);
    });

    expect(result.current.dynamicLayerTargetTime.getTime()).toBe(chosen.getTime());
  });

  it("「今」ボタンで追従へ戻る", async () => {
    stubHappyPath();

    const { result } = renderHook(() => useDynamicWeatherLayers(BASE_OPTIONS));

    act(() => result.current.setDynamicLayerTargetTime(new Date(T0 + 30 * 60 * 1000)));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11 * 60 * 1000);
    });
    act(() => result.current.handleDynamicLayerNow());

    expect(result.current.dynamicLayerTargetTime.getTime()).toBe(
      Math.floor((T0 + 11 * 60 * 1000) / STEP_MS) * STEP_MS
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(11 * 60 * 1000);
    });
    expect(result.current.dynamicLayerTargetTime.getTime()).toBe(
      Math.floor((T0 + 22 * 60 * 1000) / STEP_MS) * STEP_MS
    );
  });
});

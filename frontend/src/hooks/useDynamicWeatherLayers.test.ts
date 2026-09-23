import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDynamicWeatherLayers } from "./useDynamicWeatherLayers";
import { fetchNowcastFrames, fetchRasrfFrames, type NowcastFrame } from "@/components/Map/precipitationNowcast";
import { fetchThunderNowcastFrames } from "@/components/Map/thunderNowcast";
import { fetchLidenFrames, fetchLidenGeojson } from "@/components/Map/lidenLayer";
import { fetchCurrentRiskFrames, fetchLinearRainbandFrames } from "@/components/Map/riskMap";
import { useWeatherGrid } from "@/hooks/useWeatherGrid";
import { jmaTileFailures } from "@/components/Map/jmaTileProtocol";
import { parseJmaTileElement } from "@/components/Map/jmaNowcastFrames";

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
// 実際の記録はjmaTileProtocol.test.tsが検証する。ここは記録が状態へ届く配線だけを見る。
// useSyncExternalStoreのスナップショットのため、内容が同じなら同じ参照を返す必要がある
// （毎回新しいMapを返すと再レンダーが止まらない）。
const { noTileFailures } = vi.hoisted(() => ({ noTileFailures: new Map<string, string>() }));
vi.mock("@/components/Map/jmaTileProtocol", () => ({
  jmaTileFailures: vi.fn(() => noTileFailures),
  subscribeJmaTileFailures: () => () => {},
}));

const EMPTY_CURRENT_RISK_FRAMES = { land: [], heavyRain: [], inundation: [], flood: [] };

// 表示状態はレイヤーごとのbooleanではなく`MapLayerVisibility`1つで渡る。テストも
// そのまま同じ形で組み、必要なレイヤーだけ`shown()`でONにする。
import { buildDefaultLayerVisibility, type MapLayerId } from "@/components/Map/mapLayers";
import { useDepartureTime } from "./useDepartureTime";

const FIVE_MIN_MS = 5 * 60 * 1000;
// 表示する時刻。実データ側のフレームも「今」を5分へ丸めた時刻から始まる。
const NOW = new Date(Math.floor(Date.now() / FIVE_MIN_MS) * FIVE_MIN_MS);

const BASE_OPTIONS = {
  visibility: buildDefaultLayerVisibility(),
  hiddenDisasterSources: [],
  mapViewport: null,
  at: NOW,
  now: NOW,
};

function shown(...layerIds: MapLayerId[]) {
  const visibility = { ...buildDefaultLayerVisibility() };
  for (const id of layerIds) visibility[id] = true;
  return { ...BASE_OPTIONS, visibility };
}

/** Date → 気象庁のタイムスタンプ形式（YYYYMMDDHHmmss、UTC）。 */
function jmaTimestamp(time: Date): string {
  return time.toISOString().replace(/[-:T]/g, "").slice(0, 14);
}

function stubHappyPath() {
  vi.mocked(jmaTileFailures).mockReturnValue(noTileFailures);
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

    const { result } = renderHook(() => useDynamicWeatherLayers(shown("precipitationNowcast", "disaster")));

    await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
    await waitFor(() => expect(fetchLinearRainbandFrames).toHaveBeenCalled());
    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).toBe("empty"));
    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("empty"));
  });

  it("キキクル（現在のリスク分布）の取得失敗が、災害チップ1つ分のdynamicWeatherDataStatusへ反映される", async () => {
    stubHappyPath();
    vi.mocked(fetchCurrentRiskFrames).mockRejectedValue(new Error("kikkuru boom"));

    const { result } = renderHook(() => useDynamicWeatherLayers(shown("disaster")));

    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error"));
  });

  it("線状降水帯予測マップの取得失敗が、降水チップON時にdynamicWeatherDataStatus.precipitationNowcastへ反映される", async () => {
    stubHappyPath();
    vi.mocked(fetchLinearRainbandFrames).mockRejectedValue(new Error("linear rainband boom"));

    const { result } = renderHook(() => useDynamicWeatherLayers(shown("precipitationNowcast")));

    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).toBe("error"));
  });

  it("線状降水帯予測マップの取得失敗は、降水チップOFF時はフェッチ自体走らずdynamicWeatherDataStatusに反映されない", async () => {
    stubHappyPath();

    renderHook(() => useDynamicWeatherLayers(shown("disaster")));

    await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
    expect(fetchLinearRainbandFrames).not.toHaveBeenCalled();
  });

  describe("dynamicWeatherDataStatus（改善計画T608: MapLibreのソースイベントを経由しない統一IF）", () => {
    it("フェッチが解決するまでloading、解決後はpayloadの有無に応じてempty/正常になる", async () => {
      let resolveFetch!: (frames: Awaited<ReturnType<typeof fetchThunderNowcastFrames>>) => void;
      vi.mocked(fetchThunderNowcastFrames).mockReturnValue(
        new Promise((resolve) => {
          resolveFetch = resolve;
        }),
      );

      const { result } = renderHook(() => useDynamicWeatherLayers(shown("disaster")));

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

      const { result } = renderHook(() => useDynamicWeatherLayers(shown("windVector")));

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

  // 配信元のタイルが返らない状態は空タイルで代替されるため、フェッチ側は正常のまま
  // （jmaTileProtocol.ts）。キキクルのように「平常時は透明」が正常系のレイヤーでは、
  // 状態が出ないかぎり利用者が危険度ゼロと読む。
  describe("タイル配信の障害", () => {
    const RISK_FRAME = {
      time: new Date("2026-09-14T12:30:00Z"),
      ref: { basetime: "20260914123000", validtime: "20260914123000", member: "immed0" },
    };

    it("表示中のキキクルのタイルが返らなければ、フェッチが正常でもerrorになる", async () => {
      stubHappyPath();
      vi.mocked(fetchCurrentRiskFrames).mockResolvedValue({
        ...EMPTY_CURRENT_RISK_FRAMES,
        land: [RISK_FRAME],
      });

      const { result, rerender } = renderHook(() => useDynamicWeatherLayers(shown("disaster")));
      await waitFor(() => expect(result.current.dynamicWeather.disaster?.landslide?.payload).toBeDefined());

      const payload = result.current.dynamicWeather.disaster?.landslide?.payload;
      const template = payload?.kind === "rasterTile" ? payload.tileUrlTemplate : "";
      const ref = parseJmaTileElement(template);
      expect(ref).not.toBeNull();
      vi.mocked(jmaTileFailures).mockReturnValue(new Map([[ref!.element, ref!.prefix]]));

      // 購読の通知はこのモックが持たないため、再レンダーでスナップショットを読み直させる。
      rerender();
      await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error"));
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

      renderHook(() => useDynamicWeatherLayers(shown("disaster")));

      await waitFor(() => expect(fetchCurrentRiskFrames).toHaveBeenCalled());
      expect(fetchThunderNowcastFrames).toHaveBeenCalled();
      expect(fetchLidenFrames).toHaveBeenCalled();
    });

    it("7ソースすべてが1つのチップのON/OFFに連動し、payloadはデータのある要素にだけ載る", async () => {
      stubHappyPath();
      const frame = [{ time: new Date(), ref: { basetime: "0", validtime: "0", member: "" } }];
      vi.mocked(fetchCurrentRiskFrames).mockResolvedValue({ land: frame, heavyRain: frame, inundation: [], flood: [] });

      const { result } = renderHook(() => useDynamicWeatherLayers(shown("disaster")));

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
          ...shown("disaster"),
          hiddenDisasterSources: ["thunder", "tornado", "liden"],
        }),
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
          ...shown("disaster"),
          hiddenDisasterSources: ["heavyRain", "landslide", "inundation", "flood", "liden"],
        }),
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

      const { result } = renderHook(() => useDynamicWeatherLayers(shown("disaster")));

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

      const { result } = renderHook(() => useDynamicWeatherLayers(shown("disaster")));

      await waitFor(() =>
        expect(result.current.dynamicWeather.disaster?.liden?.payload).toEqual({ kind: "gridMark", geojson }),
      );
    });

    // 配信元の観測は「今」より遅れて届く（実測5〜10分、T861）。共有時刻は5分刻みで「今」へ
    // 追従するため最新フレームより後ろに来るのが常態で、範囲外で描かない規約をそのまま
    // 当てると雷放電は常に描画されない（本番実測: 最新フレーム22:55に対し共有時刻23:00）。
    it("最新フレームが配信の遅れのぶん過去でも、最新の観測を描く", async () => {
      stubHappyPath();
      const sharedTime = Math.floor(Date.now() / FIVE_MIN_MS) * FIVE_MIN_MS;
      const delayed = jmaTimestamp(new Date(sharedTime - FIVE_MIN_MS));
      vi.mocked(fetchLidenFrames).mockResolvedValue([{ basetime: delayed, validtime: delayed, isForecast: false }]);
      const geojson = { type: "FeatureCollection" as const, features: [] };
      vi.mocked(fetchLidenGeojson).mockResolvedValue(geojson);

      const { result } = renderHook(() => useDynamicWeatherLayers(shown("disaster")));

      await waitFor(() =>
        expect(result.current.dynamicWeather.disaster?.liden?.payload).toEqual({ kind: "gridMark", geojson }),
      );
    });
  });
});

describe("出発時刻と気象レイヤー", () => {
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
      frames.push({
        basetime: jmaTimestamp(new Date(observed)),
        validtime: jmaTimestamp(new Date(observed + offset)),
        isForecast: true,
      });
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

  it("出発時刻が「今」へ追従して進む間は、実況が更新されても降水が消えない", async () => {
    stubHappyPath();
    vi.mocked(fetchNowcastFrames).mockImplementation(async () => nowcastFramesForNow());

    const { result } = renderHook(() => {
      const departure = useDepartureTime();
      return useDynamicWeatherLayers({ ...shown("precipitationNowcast"), at: departure.at, now: departure.now });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.dynamicWeather.precipitationNowcast?.main?.payload).toBeDefined();

    // 実況が2回更新される長さ。時刻が止まっていればここで範囲外へ落ちる。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11 * 60 * 1000);
    });
    expect(result.current.dynamicWeather.precipitationNowcast?.main?.payload).toBeDefined();
  });
});

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildDefaultLayerVisibility, type MapLayerVisibility } from "@/features/map/layers/mapLayers";
import { jmaDelivery, type JmaNowcastFrame } from "@/features/map/layers/jmaNowcastFrames";
import type { WindGridPoint } from "@/types/weather";

// 配信元への取得は差し替え、時刻一覧から描画内容を組み立てる部分は本物を通す。
const fetchers = vi.hoisted(() => ({
  fetchNowcastFrames: vi.fn(),
  fetchRasrfFrames: vi.fn(),
  fetchThunderNowcastFrames: vi.fn(),
  fetchLidenFrames: vi.fn(),
  fetchLidenGeojson: vi.fn(),
  fetchCurrentRiskFrames: vi.fn(),
  fetchLinearRainbandFrames: vi.fn(),
  useWeatherGrid: vi.fn(),
  failures: { current: new Map<string, string>() as ReadonlyMap<string, string>, listeners: new Set<() => void>() },
}));
vi.mock("@/features/map/layers/precipitationNowcast", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  fetchNowcastFrames: fetchers.fetchNowcastFrames,
  fetchRasrfFrames: fetchers.fetchRasrfFrames,
}));
vi.mock("@/features/map/layers/thunderNowcast", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  fetchThunderNowcastFrames: fetchers.fetchThunderNowcastFrames,
}));
vi.mock("@/features/map/layers/lidenLayer", () => ({
  fetchLidenFrames: fetchers.fetchLidenFrames,
  fetchLidenGeojson: fetchers.fetchLidenGeojson,
}));
vi.mock("@/features/map/layers/riskMap", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  fetchCurrentRiskFrames: fetchers.fetchCurrentRiskFrames,
  fetchLinearRainbandFrames: fetchers.fetchLinearRainbandFrames,
}));
vi.mock("@/features/map/useWeatherGrid", () => ({ useWeatherGrid: fetchers.useWeatherGrid }));
vi.mock("@/features/map/layers/jmaTileProtocol", () => ({
  jmaTileFailures: () => fetchers.failures.current,
  subscribeJmaTileFailures: (listener: () => void) => {
    fetchers.failures.listeners.add(listener);
    return () => fetchers.failures.listeners.delete(listener);
  },
}));

import { useDynamicWeatherLayers } from "./useDynamicWeatherLayers";

const THUNDER = jmaDelivery("disaster/thunder").id;
const TORNADO = jmaDelivery("disaster/tornado").id;

// 日本時間 9:05（協定世界時 0:05）の出発時刻。
const NOW = new Date("2026-09-24T00:05:00Z");
const utc = (hhmm: string) => `20260924${hhmm}00`;
const frame = (validtime: string, basetime = utc("0005")): JmaNowcastFrame => ({
  basetime,
  validtime,
  isForecast: validtime > basetime,
});
// 実況は 23:55・0:05、予測は 0:15・0:25（協定世界時）。
const NOWCAST = [frame("20260923235500", "20260923235500"), frame(utc("0005")), frame(utc("0015")), frame(utc("0025"))];
const riskFrame = (basetime: string) => ({ time: new Date(), ref: { basetime, validtime: basetime, member: "none" } });

const gridPoint = (times: string[]): WindGridPoint =>
  ({
    latitude: 35,
    longitude: 139,
    times,
    wind_speed_ms: times.map(() => 3),
    wind_direction_deg: times.map(() => 0),
    precipitation_mm: times.map(() => 2),
  }) as WindGridPoint;
const GRID = [gridPoint(["2026-09-24T09:00", "2026-09-24T10:00"])];

async function settle() {
  await act(async () => {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

function visibility(on: Partial<MapLayerVisibility>): MapLayerVisibility {
  return { ...buildDefaultLayerVisibility(), disaster: false, route: false, ...on };
}

beforeEach(() => {
  fetchers.fetchNowcastFrames.mockReset().mockResolvedValue(NOWCAST);
  fetchers.fetchRasrfFrames.mockReset().mockResolvedValue([]);
  fetchers.fetchThunderNowcastFrames.mockReset().mockResolvedValue(NOWCAST);
  fetchers.fetchLidenFrames.mockReset().mockResolvedValue(NOWCAST.slice(0, 2));
  fetchers.fetchLidenGeojson.mockReset().mockImplementation(async (lidenFrame: JmaNowcastFrame) => ({
    type: "FeatureCollection",
    features: [],
    id: lidenFrame.validtime,
  }));
  fetchers.fetchCurrentRiskFrames.mockReset().mockResolvedValue({
    land: [riskFrame(utc("0000"))],
    heavyRain: [riskFrame(utc("0000"))],
    inundation: [],
    flood: [riskFrame(utc("0000"))],
  });
  fetchers.fetchLinearRainbandFrames.mockReset().mockResolvedValue([riskFrame(utc("0000"))]);
  fetchers.useWeatherGrid.mockReset().mockReturnValue({
    grid: GRID,
    detailGrid: [],
    effectiveGrid: GRID,
    effectiveGridSpacingDeg: 0.1,
    loading: false,
    error: null,
    hasFetched: true,
  });
  fetchers.failures.current = new Map();
});

type Options = Parameters<typeof useDynamicWeatherLayers>[0];
function render(options: Partial<Options> = {}) {
  const initialProps: Options = {
    visibility: visibility({}),
    hiddenDisasterSources: [],
    mapViewport: null,
    at: NOW,
    now: NOW,
    ...options,
  };
  return renderHook((props: Options) => useDynamicWeatherLayers(props), { initialProps });
}

describe("取りに行くかどうか", () => {
  it("チップがOFFの間は何も取りに行かない", async () => {
    render();
    await settle();
    for (const fetcher of [
      fetchers.fetchNowcastFrames,
      fetchers.fetchRasrfFrames,
      fetchers.fetchThunderNowcastFrames,
      fetchers.fetchLidenFrames,
      fetchers.fetchCurrentRiskFrames,
      fetchers.fetchLinearRainbandFrames,
    ]) {
      expect(fetcher).not.toHaveBeenCalled();
    }
    expect(fetchers.useWeatherGrid).toHaveBeenLastCalledWith(false, null);
  });

  it("降水はナウキャスト・短時間予報・線状降水帯・延長予報の格子を取り、風は格子だけを取る", async () => {
    const precipitation = render({ visibility: visibility({ precipitationNowcast: true }) });
    await settle();
    expect(fetchers.fetchNowcastFrames).toHaveBeenCalled();
    expect(fetchers.fetchRasrfFrames).toHaveBeenCalled();
    expect(fetchers.fetchLinearRainbandFrames).toHaveBeenCalled();
    expect(fetchers.useWeatherGrid).toHaveBeenLastCalledWith(true, null);
    precipitation.unmount();

    fetchers.fetchNowcastFrames.mockClear();
    render({ visibility: visibility({ windVector: true }) });
    await settle();
    expect(fetchers.fetchNowcastFrames).not.toHaveBeenCalled();
    expect(fetchers.useWeatherGrid).toHaveBeenLastCalledWith(true, null);
  });

  it("災害は、同じ時刻一覧を読む要素がすべて非表示の単位だけ取りに行かない", async () => {
    render({
      visibility: visibility({ disaster: true }),
      hiddenDisasterSources: ["thunder", "tornado", "liden"],
    });
    await settle();
    expect(fetchers.fetchCurrentRiskFrames).toHaveBeenCalled();
    expect(fetchers.fetchThunderNowcastFrames).not.toHaveBeenCalled();
    expect(fetchers.fetchLidenFrames).not.toHaveBeenCalled();
  });
});

describe("選んだ時刻に描くもの", () => {
  it("降水は最新の実況から先を描き、それより前（過去）の時刻では描かない", async () => {
    const { result, rerender } = render({ visibility: visibility({ precipitationNowcast: true }) });
    await settle();
    expect(result.current.dynamicWeather.precipitationNowcast?.main).toMatchObject({
      visible: true,
      payload: { kind: "rasterTile", tileUrlTemplate: expect.stringContaining(`/none/${utc("0005")}/surf/`) },
    });

    rerender({
      visibility: visibility({ precipitationNowcast: true }),
      hiddenDisasterSources: [],
      mapViewport: null,
      at: new Date("2026-09-23T23:50:00Z"),
      now: NOW,
    });
    expect(result.current.dynamicWeather.precipitationNowcast?.main?.payload).toBeUndefined();
  });

  it("ナウキャストより先は、延長予報の格子を塗る", async () => {
    const { result } = render({
      visibility: visibility({ precipitationNowcast: true }),
      at: new Date("2026-09-24T10:00:00+09:00"),
    });
    await settle();
    expect(result.current.dynamicWeather.precipitationNowcast?.main?.payload?.kind).toBe("gridFill");
  });

  it("風は格子のその時刻の矢印", async () => {
    const { result } = render({ visibility: visibility({ windVector: true }) });
    await settle();
    expect(result.current.dynamicWeather.windVector?.arrow).toMatchObject({
      visible: true,
      payload: { kind: "gridMark" },
    });
  });

  it("雷と竜巻は同じコマの、それぞれの要素のタイル。範囲の外の時刻では描かない", async () => {
    const { result, rerender } = render({ visibility: visibility({ disaster: true }) });
    await settle();
    const { thunder, tornado } = result.current.dynamicWeather.disaster ?? {};
    expect(thunder?.payload).toMatchObject({
      tileUrlTemplate: expect.stringContaining(`/${utc("0005")}/surf/${THUNDER}/`),
    });
    expect(tornado?.payload).toMatchObject({
      tileUrlTemplate: expect.stringContaining(`/${utc("0005")}/surf/${TORNADO}/`),
    });

    rerender({
      visibility: visibility({ disaster: true }),
      hiddenDisasterSources: [],
      mapViewport: null,
      at: new Date("2026-09-24T03:00:00Z"),
      now: NOW,
    });
    expect(result.current.dynamicWeather.disaster?.thunder?.payload).toBeUndefined();
  });

  it("キキクルは選んだ時刻に関わらず「現在」の危険度を描き、取れていない要素は描かない", async () => {
    const { result } = render({ visibility: visibility({ disaster: true }), at: new Date("2026-09-24T12:00:00Z") });
    await settle();
    const disaster = result.current.dynamicWeather.disaster ?? {};
    expect(disaster.landslide?.payload?.kind).toBe("rasterTile");
    expect(disaster.flood?.payload?.kind).toBe("vectorTile");
    expect(disaster.inundation?.payload).toBeUndefined();
  });

  it("線状降水帯は、今から3時間先までの時刻を選んでいる間だけ重ねる", async () => {
    const { result, rerender } = render({ visibility: visibility({ precipitationNowcast: true }) });
    await settle();
    expect(result.current.dynamicWeather.precipitationNowcast?.linearRainband?.payload?.kind).toBe("rasterTile");
    rerender({
      visibility: visibility({ precipitationNowcast: true }),
      hiddenDisasterSources: [],
      mapViewport: null,
      at: new Date(NOW.getTime() + 3 * 60 * 60 * 1000 + 60_000),
      now: NOW,
    });
    expect(result.current.dynamicWeather.precipitationNowcast?.linearRainband?.payload).toBeUndefined();
  });

  it("▶パネルで非表示にした災害の要素は、描く内容があっても非表示", async () => {
    const { result } = render({ visibility: visibility({ disaster: true }), hiddenDisasterSources: ["landslide"] });
    await settle();
    expect(result.current.dynamicWeather.disaster?.landslide?.visible).toBe(false);
    expect(result.current.dynamicWeather.disaster?.heavyRain?.visible).toBe(true);
  });
});

describe("落雷（観測だけが届く要素）", () => {
  const liden = (at: Date) =>
    render({ visibility: visibility({ disaster: true }), hiddenDisasterSources: ["thunder", "tornado"], at });

  it("配信の遅れの間は最新の観測の地点を取って描く", async () => {
    const { result } = liden(new Date("2026-09-24T00:15:00Z"));
    await settle();
    expect(fetchers.fetchLidenGeojson).toHaveBeenLastCalledWith(NOWCAST[1]);
    expect(result.current.dynamicWeather.disaster?.liden?.payload).toMatchObject({
      kind: "gridMark",
      geojson: { id: utc("0005") },
    });
  });

  it("遅れの幅より先の時刻では描かない", async () => {
    const { result } = liden(new Date("2026-09-24T01:00:00Z"));
    await settle();
    expect(result.current.dynamicWeather.disaster?.liden?.payload).toBeUndefined();
  });

  it("コマを動かした後に前のコマの地点が届いても使わず、取得の失敗では描かない", async () => {
    let resolveLatest!: (geojson: unknown) => void;
    fetchers.fetchLidenGeojson
      .mockImplementationOnce(() => new Promise((resolve) => (resolveLatest = resolve)))
      .mockRejectedValueOnce(new Error("取れません"));
    const { result, rerender } = liden(NOW);
    await settle();
    rerender({
      visibility: visibility({ disaster: true }),
      hiddenDisasterSources: ["thunder", "tornado"],
      mapViewport: null,
      at: new Date("2026-09-23T23:55:00Z"),
      now: NOW,
    });
    await settle();
    resolveLatest({ type: "FeatureCollection", features: [], id: "stale" });
    await settle();
    expect(result.current.dynamicWeather.disaster?.liden?.payload).toBeUndefined();
  });
});

describe("取得状態", () => {
  it("グループ内のどれかが描けていれば空とせず、どれも描けず取り終えていれば空", async () => {
    const { result } = render({ visibility: visibility({ disaster: true }) });
    await settle();
    expect(result.current.dynamicWeatherDataStatus.disaster).toBeUndefined();

    fetchers.fetchCurrentRiskFrames.mockResolvedValue({ land: [], heavyRain: [], inundation: [], flood: [] });
    fetchers.fetchThunderNowcastFrames.mockResolvedValue([]);
    fetchers.fetchLidenFrames.mockResolvedValue([]);
    const empty = render({ visibility: visibility({ disaster: true }) });
    await settle();
    expect(empty.result.current.dynamicWeatherDataStatus.disaster).toBe("empty");
  });

  it("グループ内のどの取得が失敗しても失敗", async () => {
    fetchers.fetchRasrfFrames.mockRejectedValue(new Error("短時間予報を取れません"));
    const { result } = render({ visibility: visibility({ precipitationNowcast: true }) });
    await settle();
    expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).toBe("error");
  });

  it("表示中のタイルの配信が止まっていれば、取得が成功していても失敗", async () => {
    const { result } = render({ visibility: visibility({ disaster: true }) });
    await settle();
    const url = result.current.dynamicWeather.disaster?.thunder?.payload;
    const template = url && "tileUrlTemplate" in url ? url.tileUrlTemplate : "";
    act(() => {
      fetchers.failures.current = new Map([[THUNDER, template.slice(0, template.indexOf("{z}"))]]);
      fetchers.failures.listeners.forEach((listener) => listener());
    });
    expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error");
  });
});

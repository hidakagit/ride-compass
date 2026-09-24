import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildDefaultLayerVisibility, type MapLayerVisibility } from "@/features/map/layers/mapLayers";
import type { JmaDelivery, JmaFrame } from "@/features/map/layers/jmaDelivery";
import { WEATHER_SOURCES, type WeatherSource } from "@/features/map/layers/weatherSources";
import type { WindGridPoint } from "@/types/weather";

// 配信元への取得は差し替え、段のつなぎ・コマの選び方・描画内容の組み立ては本物を通す。
const fetchers = vi.hoisted(() => ({
  fetchJmaFrames: vi.fn(),
  fetchJmaPointGeojson: vi.fn(),
  useWeatherGrid: vi.fn(),
  failures: { current: new Map<string, string>() as ReadonlyMap<string, string>, listeners: new Set<() => void>() },
}));
vi.mock("@/features/map/layers/jmaDelivery", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  fetchJmaFrames: fetchers.fetchJmaFrames,
  fetchJmaPointGeojson: fetchers.fetchJmaPointGeojson,
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

const source = (group: string, name: string) =>
  WEATHER_SOURCES.find((entry) => entry.group === group && entry.source === name)!;
const jmaDeliveries = (entry: WeatherSource) =>
  entry.stages.flatMap((stage) => (stage.origin === "jma" ? [stage.delivery] : []));
const idsOf = (sources: readonly WeatherSource[]) =>
  [...new Set(sources.flatMap(jmaDeliveries).map((d) => d.id))].sort();
const inGroup = (group: string) => WEATHER_SOURCES.filter((entry) => entry.group === group);

// 日本時間 9:05（協定世界時 0:05）の出発時刻。
const NOW = new Date("2026-09-24T00:05:00Z");
const utc = (hhmm: string) => `20260924${hhmm}00`;
const frame = (validtime: string, basetime = utc("0005")): JmaFrame => ({ basetime, member: "none", validtime });
// 読み方ごとの応答。実況＋予測は 0:05（実況）・0:15・0:25、現在の単一値は 0:00 の1コマ。
const NOWCAST = [frame(utc("0005")), frame(utc("0015")), frame(utc("0025"))];
const CURRENT = [frame(utc("0000"), utc("0000"))];
const FRAMES_BY_READER: Record<JmaDelivery["reader"], JmaFrame[]> = {
  nowcast: NOWCAST,
  latestFullRun: [],
  latest: CURRENT,
};

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
  fetchers.fetchJmaFrames
    .mockReset()
    .mockImplementation(async (delivery: JmaDelivery) => FRAMES_BY_READER[delivery.reader]);
  fetchers.fetchJmaPointGeojson
    .mockReset()
    .mockImplementation(async (_delivery: JmaDelivery, pointFrame: JmaFrame) => ({
      type: "FeatureCollection",
      features: [],
      id: pointFrame.validtime,
    }));
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
    hiddenSources: {},
    mapViewport: null,
    at: NOW,
    now: NOW,
    ...options,
  };
  return renderHook((props: Options) => useDynamicWeatherLayers(props), { initialProps });
}
const fetchedIds = () =>
  [...new Set(fetchers.fetchJmaFrames.mock.calls.map((call) => (call[0] as JmaDelivery).id))].sort();

describe("取りに行くかどうか", () => {
  it("チップがOFFの間は何も取りに行かない", async () => {
    render();
    await settle();
    expect(fetchers.fetchJmaFrames).not.toHaveBeenCalled();
    expect(fetchers.useWeatherGrid).toHaveBeenLastCalledWith(false, null);
  });

  it("ONにしたチップのソースが読む配信要素と、格子を読むソースがあれば格子を取りに行く", async () => {
    const precipitation = render({ visibility: visibility({ precipitationNowcast: true }) });
    await settle();
    expect(fetchedIds()).toEqual(idsOf(inGroup("precipitationNowcast")));
    expect(fetchers.useWeatherGrid).toHaveBeenLastCalledWith(true, null);
    precipitation.unmount();

    fetchers.fetchJmaFrames.mockClear();
    render({ visibility: visibility({ windVector: true }) });
    await settle();
    expect(fetchers.fetchJmaFrames).not.toHaveBeenCalled();
    expect(fetchers.useWeatherGrid).toHaveBeenLastCalledWith(true, null);
  });

  it("非表示にしたソースの配信要素は、表示中のソースが読まなければ取りに行かない", async () => {
    const [kept, ...hidden] = inGroup("disaster");
    render({
      visibility: visibility({ disaster: true }),
      hiddenSources: { disaster: hidden.map((entry) => entry.source) },
    });
    await settle();
    expect(fetchedIds()).toEqual(idsOf([kept]));
  });
});

describe("選んだ時刻に描くもの", () => {
  const precipitation = () => render({ visibility: visibility({ precipitationNowcast: true }) });

  it("一番近いコマの規則: 最新の実況から先を描き、それより前（過去）の時刻では描かない", async () => {
    const { result, rerender } = precipitation();
    await settle();
    expect(result.current.dynamicWeather.precipitationNowcast?.main).toMatchObject({
      visible: true,
      payload: { kind: "rasterTile", tileUrlTemplate: expect.stringContaining(`/none/${utc("0005")}/surf/`) },
    });

    rerender({
      visibility: visibility({ precipitationNowcast: true }),
      hiddenSources: {},
      mapViewport: null,
      at: new Date("2026-09-23T23:50:00Z"),
      now: NOW,
    });
    expect(result.current.dynamicWeather.precipitationNowcast?.main?.payload).toBeUndefined();
  });

  it("配信元の段の先は、次の段（自前の格子の塗り）が描く", async () => {
    const { result } = render({
      visibility: visibility({ precipitationNowcast: true }),
      at: new Date("2026-09-24T10:00:00+09:00"),
    });
    await settle();
    expect(result.current.dynamicWeather.precipitationNowcast?.main?.payload?.kind).toBe("gridFill");
  });

  it("格子の風は、その時刻の矢印", async () => {
    const { result } = render({ visibility: visibility({ windVector: true }) });
    await settle();
    expect(result.current.dynamicWeather.windVector?.arrow).toMatchObject({
      visible: true,
      payload: { kind: "gridMark" },
    });
  });

  it("配信元のタイルは、そのソースの配信要素の、選んだコマの時刻を指す", async () => {
    const thunder = source("disaster", "thunder");
    const { result } = render({ visibility: visibility({ disaster: true }) });
    await settle();
    expect(result.current.dynamicWeather.disaster?.thunder?.payload).toMatchObject({
      tileUrlTemplate: expect.stringContaining(`/${utc("0005")}/surf/${jmaDeliveries(thunder)[0].id}/`),
    });
  });

  it("現在の規則: 選んだ時刻に関わらず現在のコマを描き、取れていないソースは描かない", async () => {
    const [missing] = jmaDeliveries(source("disaster", "inundation"));
    fetchers.fetchJmaFrames.mockImplementation(async (delivery: JmaDelivery) =>
      delivery.id === missing.id ? [] : FRAMES_BY_READER[delivery.reader],
    );
    const { result } = render({ visibility: visibility({ disaster: true }), at: new Date("2026-09-24T12:00:00Z") });
    await settle();
    const disaster = result.current.dynamicWeather.disaster ?? {};
    expect(disaster.landslide?.payload?.kind).toBe("rasterTile");
    expect(disaster.flood?.payload?.kind).toBe("vectorTile");
    expect(disaster.inundation?.payload).toBeUndefined();
  });

  it("窓のある現在の規則: 今から窓の幅までの時刻を選んでいる間だけ描く", async () => {
    const { windowMinutes } = source("precipitationNowcast", "linearRainband").frameRule;
    const { result, rerender } = precipitation();
    await settle();
    expect(result.current.dynamicWeather.precipitationNowcast?.linearRainband?.payload?.kind).toBe("rasterTile");
    rerender({
      visibility: visibility({ precipitationNowcast: true }),
      hiddenSources: {},
      mapViewport: null,
      at: new Date(NOW.getTime() + (windowMinutes! + 1) * 60_000),
      now: NOW,
    });
    expect(result.current.dynamicWeather.precipitationNowcast?.linearRainband?.payload).toBeUndefined();
  });

  it("▶パネルで非表示にしたソースは非表示", async () => {
    const { result } = render({
      visibility: visibility({ disaster: true }),
      hiddenSources: { disaster: ["landslide"] },
    });
    await settle();
    expect(result.current.dynamicWeather.disaster?.landslide?.visible).toBe(false);
    expect(result.current.dynamicWeather.disaster?.heavyRain?.visible).toBe(true);
  });
});

describe("配信元の地点（最新の観測の規則）", () => {
  const others = inGroup("disaster")
    .filter((entry) => entry.source !== "liden")
    .map((entry) => entry.source);
  const liden = (at: Date) =>
    render({ visibility: visibility({ disaster: true }), hiddenSources: { disaster: others }, at });

  it("配信の遅れの間は最新の観測の地点を取って描く", async () => {
    const { result } = liden(new Date("2026-09-24T00:30:00Z"));
    await settle();
    expect(fetchers.fetchJmaPointGeojson).toHaveBeenLastCalledWith(
      jmaDeliveries(source("disaster", "liden"))[0],
      NOWCAST[2],
      expect.any(String),
    );
    expect(result.current.dynamicWeather.disaster?.liden?.payload).toMatchObject({
      kind: "gridMark",
      geojson: { id: utc("0025") },
    });
  });

  it("遅れの幅より先の時刻では描かない", async () => {
    const { windowMinutes } = source("disaster", "liden").frameRule;
    const { result } = liden(new Date(new Date("2026-09-24T00:25:00Z").getTime() + (windowMinutes! + 1) * 60_000));
    await settle();
    expect(result.current.dynamicWeather.disaster?.liden?.payload).toBeUndefined();
  });

  it("コマを動かした後に前のコマの地点が届いても使わず、取得の失敗では描かない", async () => {
    let resolveEarlier!: (geojson: unknown) => void;
    fetchers.fetchJmaPointGeojson
      .mockImplementationOnce(() => new Promise((resolve) => (resolveEarlier = resolve)))
      .mockRejectedValueOnce(new Error("取れません"));
    const { result, rerender } = liden(NOW);
    await settle();
    rerender({
      visibility: visibility({ disaster: true }),
      hiddenSources: { disaster: others },
      mapViewport: null,
      at: new Date("2026-09-24T00:15:00Z"),
      now: NOW,
    });
    await settle();
    resolveEarlier({ type: "FeatureCollection", features: [], id: "stale" });
    await settle();
    expect(result.current.dynamicWeather.disaster?.liden?.payload).toBeUndefined();
  });
});

describe("取得状態", () => {
  it("チップ内のどれかが描けていれば空とせず、どれも描けず取り終えていれば空", async () => {
    const { result } = render({ visibility: visibility({ disaster: true }) });
    await settle();
    expect(result.current.dynamicWeatherDataStatus.disaster).toBeUndefined();

    fetchers.fetchJmaFrames.mockResolvedValue([]);
    const empty = render({ visibility: visibility({ disaster: true }) });
    await settle();
    expect(empty.result.current.dynamicWeatherDataStatus.disaster).toBe("empty");
  });

  it("チップ内のどの取得が失敗しても失敗", async () => {
    const [failing] = idsOf(inGroup("precipitationNowcast"));
    fetchers.fetchJmaFrames.mockImplementation(async (delivery: JmaDelivery) => {
      if (delivery.id === failing) throw new Error("取れません");
      return FRAMES_BY_READER[delivery.reader];
    });
    const { result } = render({ visibility: visibility({ precipitationNowcast: true }) });
    await settle();
    expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).toBe("error");
  });

  it("表示中のタイルの配信が止まっていれば、取得が成功していても失敗", async () => {
    const { result } = render({ visibility: visibility({ disaster: true }) });
    await settle();
    const payload = result.current.dynamicWeather.disaster?.thunder?.payload;
    const template = payload && "tileUrlTemplate" in payload ? payload.tileUrlTemplate : "";
    act(() => {
      fetchers.failures.current = new Map([
        [jmaDeliveries(source("disaster", "thunder"))[0].id, template.slice(0, template.indexOf("{z}"))],
      ]);
      fetchers.failures.listeners.forEach((listener) => listener());
    });
    expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error");
  });
});

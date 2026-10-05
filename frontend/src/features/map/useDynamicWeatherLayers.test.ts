import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildDefaultLayerVisibility, type MapLayerVisibility } from "@/features/map/layers/mapLayers";
import { readJmaTileUrl, type JmaDelivery, type JmaFrame } from "@/features/map/layers/jmaDelivery";
import type { DynamicWeatherRenderPayload } from "@/features/map/layers/dynamicWeather";
import { WEATHER_SOURCES, type WeatherSource } from "@/features/map/layers/weatherSources";
import type { WindGridPoint } from "@/types/weather";

// 配信元への取得は差し替え、時刻一覧の読み方・段のつなぎ・コマの選び方・描画内容の組み立ては本物を通す。
const fetchers = vi.hoisted(() => ({
  fetchJmaTargetTimesFile: vi.fn(),
  fetchJmaGeojson: vi.fn(),
  useWeatherGrid: vi.fn(),
  failures: { current: new Map<string, string>() as ReadonlyMap<string, string>, listeners: new Set<() => void>() },
}));
vi.mock("@/features/map/layers/jmaDelivery", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  fetchJmaTargetTimesFile: fetchers.fetchJmaTargetTimesFile,
  fetchJmaGeojson: fetchers.fetchJmaGeojson,
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
const pathsOf = (sources: readonly WeatherSource[]) =>
  [...new Set(sources.flatMap(jmaDeliveries).flatMap((delivery) => delivery.targetTimesPaths))].sort();
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
const framesByReader = (delivery: JmaDelivery) => FRAMES_BY_READER[delivery.reader];

const DELIVERIES = WEATHER_SOURCES.flatMap(jmaDeliveries);
/** そのファイルの時刻一覧。そのファイルを最初の在り処とする配信要素ごとに、`framesOf`のコマを行にして並べる
 * （1つのファイルに複数の要素の行が載る）。 */
function rowsOf(path: string, framesOf: (delivery: JmaDelivery) => readonly JmaFrame[]) {
  const owners = new Map(
    DELIVERIES.filter((delivery) => delivery.targetTimesPaths[0] === path).map((delivery) => [delivery.id, delivery]),
  );
  return [...owners.values()].flatMap((delivery) =>
    framesOf(delivery).map((ownFrame) => ({ ...ownFrame, elements: [delivery.id] })),
  );
}
/** 時刻一覧を、配信要素ごとに`framesOf`のコマを返す内容にする。 */
function respondWith(framesOf: (delivery: JmaDelivery) => readonly JmaFrame[]) {
  fetchers.fetchJmaTargetTimesFile.mockImplementation(async (path: string) => rowsOf(path, framesOf));
}

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

// 取得の結果は区切り（`setTimeout(0)`）ごとに届くので、偽にしていない時計で数回区切りを待つ。
async function settle() {
  await act(async () => {
    for (let i = 0; i < 3; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function visibility(on: Partial<MapLayerVisibility>): MapLayerVisibility {
  return { ...buildDefaultLayerVisibility(), disaster: false, route: false, ...on };
}

beforeEach(() => {
  fetchers.fetchJmaTargetTimesFile.mockReset();
  respondWith(framesByReader);
  fetchers.fetchJmaGeojson.mockReset().mockImplementation(async (_delivery: JmaDelivery, selectedFrame: JmaFrame) => ({
    type: "FeatureCollection",
    features: [],
    id: selectedFrame.validtime,
  }));
  fetchers.useWeatherGrid.mockReset().mockReturnValue({
    grid: GRID,
    detail: null,
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
const fetchedPaths = () =>
  [...new Set(fetchers.fetchJmaTargetTimesFile.mock.calls.map((call) => call[0] as string))].sort();
/** 配信元のタイルの描画内容が指す配信要素とコマ（地図ライブラリがタイル座標を埋めたURLから読み戻す）。 */
const drawn = (payload: DynamicWeatherRenderPayload | undefined) =>
  payload && "tileUrlTemplate" in payload
    ? readJmaTileUrl(payload.tileUrlTemplate.replace("{z}", "4").replace("{x}", "14").replace("{y}", "6"))
    : null;

describe("取りに行くかどうか", () => {
  it("チップがOFFの間は何も取りに行かない", async () => {
    render();
    await settle();
    expect(fetchers.fetchJmaTargetTimesFile).not.toHaveBeenCalled();
    expect(fetchers.useWeatherGrid).toHaveBeenLastCalledWith(false, null);
  });

  it("ONにしたチップのソースが読む配信要素と、格子を読むソースがあれば格子を取りに行く", async () => {
    const precipitation = render({ visibility: visibility({ precipitationNowcast: true }) });
    await settle();
    expect(fetchedPaths()).toEqual(pathsOf(inGroup("precipitationNowcast")));
    expect(fetchers.useWeatherGrid).toHaveBeenLastCalledWith(true, null);
    precipitation.unmount();

    fetchers.fetchJmaTargetTimesFile.mockClear();
    render({ visibility: visibility({ windVector: true }) });
    await settle();
    expect(fetchers.fetchJmaTargetTimesFile).not.toHaveBeenCalled();
    expect(fetchers.useWeatherGrid).toHaveBeenLastCalledWith(true, null);
  });

  it("非表示にしたソースの配信要素は、表示中のソースが読まなければ取りに行かない", async () => {
    const [kept, ...hidden] = inGroup("disaster");
    render({
      visibility: visibility({ disaster: true }),
      hiddenSources: { disaster: hidden.map((entry) => entry.source) },
    });
    await settle();
    expect(fetchedPaths()).toEqual(pathsOf([kept]));
  });
});

describe("選んだ時刻に描くもの", () => {
  it("配信元の段の先は、次の段（自前の格子の塗り）が描く", async () => {
    const { result } = render({
      visibility: visibility({ precipitationNowcast: true }),
      at: new Date("2026-09-24T10:00:00+09:00"),
    });
    await settle();
    expect(result.current.dynamicWeather.precipitationNowcast?.main?.payload?.kind).toBe("gridFill");
  });

  it("配信元のタイルは、そのソースの配信要素の、選んだコマの時刻を指す", async () => {
    const thunder = source("disaster", "thunder");
    const { result } = render({ visibility: visibility({ disaster: true }) });
    await settle();
    expect(drawn(result.current.dynamicWeather.disaster?.thunder?.payload)).toMatchObject({
      delivery: jmaDeliveries(thunder)[0],
      frame: { validtime: utc("0005") },
    });
  });

  it("現在の規則: 選んだ時刻に関わらず現在のコマを描き、取れていないソースは描かない", async () => {
    const [missing] = jmaDeliveries(source("disaster", "inundation"));
    respondWith((delivery) => (delivery.id === missing.id ? [] : framesByReader(delivery)));
    const { result } = render({ visibility: visibility({ disaster: true }), at: new Date("2026-09-24T12:00:00Z") });
    await settle();
    const disaster = result.current.dynamicWeather.disaster ?? {};
    expect(disaster.landslide?.payload?.kind).toBe("rasterTile");
    expect(disaster.flood?.payload?.kind).toBe("vectorTile");
    expect(disaster.inundation?.payload).toBeUndefined();
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

describe("格子の段と詳細格子（ズームしたとき）", () => {
  // 値は時刻の「時」そのもの。backendは取った時点の正時から先を返すので、粗い格子は13時に、詳細格子はそれより前の
  // 10時に取ったものとして、時刻の列の先頭が違う。
  const hourly = (latitude: number, startHour: number): WindGridPoint => {
    const times = Array.from({ length: 6 }, (_, i) => `2026-09-24T${String(startHour + i).padStart(2, "0")}:00`);
    return {
      latitude,
      longitude: 139,
      times,
      wind_speed_ms: times.map((time) => Number(time.slice(11, 13))),
      wind_direction_deg: times.map(() => 0),
      precipitation_mm: times.map(() => 0),
    } as WindGridPoint;
  };
  const arrowsAt = (at: Date) => {
    fetchers.useWeatherGrid.mockReturnValue({
      grid: [hourly(35, 13)],
      detail: { spacingDeg: 0.01, points: [hourly(35.61, 10)] },
      loading: false,
      error: null,
      hasFetched: true,
    });
    const { result } = render({ visibility: visibility({ windVector: true }), at, now: at });
    const payload = result.current.dynamicWeather.windVector?.arrow?.payload;
    const features = payload?.kind === "gridMark" ? payload.geojson.features : [];
    return features.map((feature) => [(feature.geometry as GeoJSON.Point).coordinates[1], feature.properties?.speed]);
  };

  it("粗い格子と詳細格子を取った時刻が違っても、詳細格子の選んだ時刻の値を描く", () => {
    expect(arrowsAt(new Date("2026-09-24T13:20:00+09:00"))).toEqual([[35.61, 13]]);
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
    expect(fetchers.fetchJmaGeojson).toHaveBeenLastCalledWith(
      jmaDeliveries(source("disaster", "liden"))[0],
      NOWCAST[2],
      expect.any(String),
    );
    expect(result.current.dynamicWeather.disaster?.liden?.payload).toMatchObject({
      kind: "gridMark",
      geojson: { id: utc("0025") },
    });
  });

  it("地点の取得に失敗したコマは描かず、チップは「値なし」ではなく失敗", async () => {
    fetchers.fetchJmaGeojson.mockRejectedValue(new Error("取れません"));
    const { result } = liden(NOW);
    await settle();
    expect(fetchers.fetchJmaGeojson).toHaveBeenCalled();
    expect(result.current.dynamicWeather.disaster?.liden?.payload).toBeUndefined();
    expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error");
  });

  it("地点を取っている間は「値なし」ではなく読み込み中", async () => {
    fetchers.fetchJmaGeojson.mockImplementation(() => new Promise(() => {}));
    const { result } = liden(NOW);
    await settle();
    expect(result.current.dynamicWeatherDataStatus.disaster).toBe("loading");
  });
});

describe("配信元の領域（線状降水帯の雨域）", () => {
  const area = source("precipitationNowcast", "linearRainbandArea");
  const [delivery] = jmaDeliveries(area);
  const others = inGroup("precipitationNowcast")
    .filter((entry) => entry !== area)
    .map((entry) => entry.source);

  it("時刻一覧の最新のbasetimeは配信の遅れのぶん前のbasetimeで取り、選んだ時刻の領域を輪郭線として描く", async () => {
    // 時刻一覧の最新の予測の先端（0:25）。配信済みの前のbasetimeの予測が届く。
    const at = new Date("2026-09-24T00:25:00Z");
    const { result } = render({
      visibility: visibility({ precipitationNowcast: true }),
      hiddenSources: { precipitationNowcast: others },
      at,
    });
    await settle();
    const delivered = new Date(NOW.getTime() - delivery.dataDelayMinutes * 60_000);
    expect(fetchers.fetchJmaGeojson).toHaveBeenLastCalledWith(
      delivery,
      frame(utc("0025"), delivered.toISOString().replace(/[-:T]/g, "").slice(0, 14)),
      expect.any(String),
    );
    expect(result.current.dynamicWeather.precipitationNowcast?.linearRainbandArea).toMatchObject({
      visible: true,
      payload: { kind: "outline", geojson: { id: utc("0025") } },
    });
  });
});

describe("時刻一覧が複数のファイルに分かれる要素", () => {
  const split = DELIVERIES.find((delivery) => delivery.targetTimesPaths.length > 1)!;
  const owner = WEATHER_SOURCES.find((entry) => jmaDeliveries(entry).includes(split))!;
  const others = inGroup(owner.group)
    .filter((entry) => entry !== owner)
    .map((entry) => entry.source);
  const show = () =>
    render({ visibility: visibility({ [owner.group]: true }), hiddenSources: { [owner.group]: others } });
  const splitFiles: readonly string[] = split.targetTimesPaths;
  const failFiles = (failing: readonly string[]) =>
    fetchers.fetchJmaTargetTimesFile.mockImplementation(async (path: string) => {
      if (failing.includes(path)) throw new Error("取れません");
      if (splitFiles.includes(path)) return NOWCAST.map((ownFrame) => ({ ...ownFrame, elements: [split.id] }));
      return rowsOf(path, framesByReader);
    });

  it("一部のファイルだけ取れなくても、残りのファイルの行で描く", async () => {
    failFiles(splitFiles.slice(0, 1));
    const { result } = show();
    await settle();
    expect(result.current.dynamicWeather[owner.group]?.[owner.source]?.payload).toBeDefined();
    expect(result.current.dynamicWeatherDataStatus[owner.group]).toBeUndefined();
  });

  it("全部のファイルが取れないときだけ失敗", async () => {
    failFiles(splitFiles);
    const { result } = show();
    await settle();
    expect(result.current.dynamicWeatherDataStatus[owner.group]).toBe("error");
  });
});

describe("取得状態", () => {
  it("まだ取り終えていない間は読み込み中、格子を読むチップは格子の取得の失敗をそのまま出す", async () => {
    fetchers.fetchJmaTargetTimesFile.mockImplementation(() => new Promise(() => {}));
    fetchers.useWeatherGrid.mockReturnValue({
      grid: [],
      detail: null,
      loading: false,
      error: "格子を取れません",
      hasFetched: true,
    });
    const { result } = render({ visibility: visibility({ disaster: true, windVector: true }) });
    await settle();
    expect(result.current.dynamicWeatherDataStatus).toMatchObject({ disaster: "loading", windVector: "error" });
  });

  it("OFFのチップは取りに行っていないので、何も言わない（「データが無い」と断定しない）", async () => {
    fetchers.useWeatherGrid.mockImplementation((enabled: boolean) => ({
      grid: [],
      detail: null,
      loading: false,
      error: null,
      hasFetched: enabled,
    }));
    const { result } = render();
    await settle();
    expect(Object.values(result.current.dynamicWeatherDataStatus).every((status) => status === undefined)).toBe(true);
  });

  it("チップ内のどれかが描けていれば空とせず、どれも描けず取り終えていれば空", async () => {
    const { result } = render({ visibility: visibility({ disaster: true }) });
    await settle();
    expect(result.current.dynamicWeatherDataStatus.disaster).toBeUndefined();

    respondWith(() => []);
    const empty = render({ visibility: visibility({ disaster: true }) });
    await settle();
    expect(empty.result.current.dynamicWeatherDataStatus.disaster).toBe("empty");
  });

  it("表示中のタイルの配信が止まっていれば、取得が成功していても失敗", async () => {
    const { result } = render({ visibility: visibility({ disaster: true }) });
    await settle();
    const payload = result.current.dynamicWeather.disaster?.thunder?.payload;
    const template = payload && "tileUrlTemplate" in payload ? payload.tileUrlTemplate : "";
    act(() => {
      fetchers.failures.current = new Map([[jmaDeliveries(source("disaster", "thunder"))[0].id, template]]);
      fetchers.failures.listeners.forEach((listener) => listener());
    });
    expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error");
  });
});

describe("出発時刻が「今」へ追従しているとき", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("時間が経っても、定期的に取り直した時刻一覧で「今」の降水を描き続ける（過去に取り残されない）", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    // 配信元の「今」。取り直すたびに、その時点の実況から先の時刻一覧が返る。
    let latest = 5;
    const hhmm = (minute: number) => `00${String(minute).padStart(2, "0")}`;
    respondWith((delivery) =>
      delivery.reader === "nowcast"
        ? [frame(utc(hhmm(latest)), utc(hhmm(latest))), frame(utc(hhmm(latest + 10)), utc(hhmm(latest)))]
        : framesByReader(delivery),
    );
    const props = (at: Date): Options => ({
      visibility: visibility({ precipitationNowcast: true }),
      hiddenSources: {},
      mapViewport: null,
      at,
      now: at,
    });
    const { result, rerender } = renderHook((p: Options) => useDynamicWeatherLayers(p), { initialProps: props(NOW) });
    await settle();
    expect(result.current.dynamicWeather.precipitationNowcast?.main?.payload).toBeDefined();

    // 30分放置する。出発時刻は「今」へ追従して進み、配信元の実況も進む。
    latest = 35;
    act(() => vi.advanceTimersByTime(30 * 60 * 1000));
    await settle();
    rerender(props(new Date("2026-09-24T00:35:00Z")));
    expect(drawn(result.current.dynamicWeather.precipitationNowcast?.main?.payload)?.frame).toEqual(
      frame(utc("0035"), utc("0035")),
    );
  });
});

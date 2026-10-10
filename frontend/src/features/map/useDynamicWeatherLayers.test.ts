/**
 * 動的気象レイヤーのフックが、表示中のソースだけを配信元と backend から取り、選んだ時刻のコマの描画内容とチップの取得状態を
 * 返すことを見る（docs/modules/frontend/dynamic-weather-layers.md）。配信元の中継（時刻一覧・地物・タイル）は画面のオリジンへ、
 * 風の格子は backend へ出るので、どちらも網の層で応える。応答を与えていない要求はテストを落とすので、取りに行かないソースは
 * 応答を与えないことで確かめる。
 *
 * ここで見ないもの: 時刻一覧の行の読み方・段のつなぎ方・コマの規則（`jmaDelivery.test.ts`・`weatherSources.test.ts`）、
 * 詳細格子（`useWeatherGrid.test.ts`）、タイルの失敗の記録とコマの突き合わせ（`jmaTileProtocol.test.ts`・`dynamicWeather.test.ts`）。
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("maplibre-gl", () => import("@/testing/maplibre"));

import { jmaTilePayload } from "@/features/map/layers/jmaDelivery";
import { registerJmaTileProtocol, withJmaTileProtocol } from "@/features/map/layers/jmaTileProtocol";
import type { MapLayerVisibility } from "@/features/map/layers/mapLayers";
import { heldReplies, inTurn, onBackend, onSameOrigin } from "@/testing/backendServer";
import { protocolHandler } from "@/testing/maplibre";
import { jmaDeliveryOf, jmaTileUrlAt } from "@/testing/jmaDeliveries";

import { useDynamicWeatherLayers } from "./useDynamicWeatherLayers";

const NOW = new Date("2026-10-07T03:00:00Z");
const BASETIME = "20261007030000";
const FRAME = { basetime: BASETIME, member: "none", validtime: BASETIME };
const DISASTER_RISK = ["heavyRain", "landslide", "inundation", "flood"];
const DISASTER_NOWCAST = ["thunder", "tornado", "liden"];
const PRECIPITATION_EXCEPT_MAIN = ["linearRainband", "linearRainbandArea", "linearRainbandAreaForecast"];

const timesPath = (file: string) => `/api/jma-tile/bosai/jmatile/data/${file}`;
const rows = (...elements: string[]) => [{ ...FRAME, elements }];
const failure = () => new HttpResponse(null, { status: 500 });

type Options = Parameters<typeof useDynamicWeatherLayers>[0];

function render(shown: Partial<MapLayerVisibility>, hiddenSources: Options["hiddenSources"] = {}) {
  return renderHook(
    ({ at }: { at: Date }) =>
      useDynamicWeatherLayers({
        visibility: shown as MapLayerVisibility,
        hiddenSources,
        mapViewport: null,
        at,
        now: NOW,
      }),
    { initialProps: { at: NOW } },
  );
}

/** 風の格子。点1つが、渡した日本時間の時刻ごとに風と降水の値を持つ。 */
const windGrid = (...times: string[]) =>
  Response.json({
    times,
    points: [
      {
        latitude: 35,
        longitude: 139,
        wind_speed_ms: times.map(() => 5),
        wind_direction_deg: times.map(() => 90),
        precipitation_mm: times.map(() => 3),
      },
    ],
  });

afterEach(() => {
  vi.useRealTimers();
});

describe("useDynamicWeatherLayers", () => {
  it("表示中のソースだけを取りに行き、選んだ時刻のコマのタイルを描く（消したチップと隠したソースは描かず、チップのどれかのソースが描けていれば空としない）", async () => {
    onSameOrigin("GET", timesPath("risk/targetTimes.json"), () => Response.json(rows("rain_mesh", "land")));

    const { result } = render({ disaster: true }, { disaster: ["landslide", ...DISASTER_NOWCAST] });

    expect(result.current.dynamicWeatherDataStatus.disaster).toBe("loading");
    await waitFor(() =>
      expect(result.current.dynamicWeather.disaster?.heavyRain).toEqual({
        visible: true,
        payload: jmaTilePayload("rasterTile", jmaDeliveryOf("rain_mesh"), FRAME),
      }),
    );
    expect(result.current.dynamicWeather.disaster?.landslide).toEqual({ visible: false, payload: undefined });
    expect(result.current.dynamicWeather.precipitationNowcast?.main?.visible).toBe(false);
    expect(result.current.dynamicWeatherDataStatus).toEqual({
      disaster: undefined,
      precipitationNowcast: undefined,
      windVector: undefined,
    });
  });

  it("時刻一覧に描けるコマが無いチップは、取り終えたら空にする", async () => {
    onSameOrigin("GET", timesPath("risk/targetTimes.json"), () => Response.json([]));

    const { result } = render({ disaster: true }, { disaster: DISASTER_NOWCAST });

    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("empty"));
  });

  it.each([
    {
      name: "一部のファイルが取れなければ、残りのファイルで描く",
      n1: () => Response.json(rows("hrpns")),
      status: undefined,
      drawn: true,
    },
    { name: "全部のファイルが取れなければ、失敗にする", n1: failure, status: "error", drawn: false },
  ])("時刻一覧が複数のファイルに分かれる配信は、$name", async ({ n1, status, drawn }) => {
    onSameOrigin("GET", timesPath("nowc/targetTimes_N1.json"), n1);
    onSameOrigin("GET", timesPath("nowc/targetTimes_N2.json"), failure);
    onSameOrigin("GET", timesPath("rasrf/targetTimes.json"), () => Response.json([]));
    onBackend("GET", "/api/weather/wind-grid", () => windGrid());

    const { result } = render({ precipitationNowcast: true }, { precipitationNowcast: PRECIPITATION_EXCEPT_MAIN });

    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).not.toBe("loading"));
    expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).toBe(status);
    expect(result.current.dynamicWeather.precipitationNowcast?.main?.payload).toEqual(
      drawn ? jmaTilePayload("rasterTile", jmaDeliveryOf("hrpns"), FRAME) : undefined,
    );
  });

  it("時刻一覧の取り直しに失敗している間は、前に届いた一覧で描かずに失敗にする", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"], shouldAdvanceTime: true });
    onSameOrigin("GET", timesPath("risk/targetTimes.json"), inTurn(Response.json(rows("rain_mesh")), failure()));
    const { result } = render({ disaster: true }, { disaster: DISASTER_NOWCAST });
    await waitFor(() => expect(result.current.dynamicWeather.disaster?.heavyRain?.payload).toBeDefined());

    act(() => vi.advanceTimersByTime(jmaDeliveryOf("rain_mesh").refreshIntervalMs));

    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error"));
    expect(result.current.dynamicWeather.disaster?.heavyRain?.payload).toBeUndefined();
  });

  it("地物で描く段は選んでいるコマの地物だけを描き、取れていない間は読み込み中、取れなければ失敗にする", async () => {
    const row = (validtime: string) => ({ basetime: "20261007025500", member: "none", validtime, elements: ["liden"] });
    onSameOrigin("GET", timesPath("nowc/targetTimes_N3.json"), () =>
      Response.json([row("20261007025500"), row(BASETIME)]),
    );
    const geojson = heldReplies();
    onSameOrigin(
      "GET",
      "/api/jma-tile/bosai/jmatile/data/nowc/:basetime/none/:validtime/surf/liden/data.geojson",
      geojson.reply,
    );
    const point = { type: "Point", coordinates: [139, 35] };
    const { result, rerender } = render({ disaster: true }, { disaster: [...DISASTER_RISK, "thunder", "tornado"] });
    await waitFor(() => expect(geojson.arrived()).toBe(1));
    expect(result.current.dynamicWeatherDataStatus.disaster).toBe("loading");

    // 前のコマへ動かしたあとに、後のコマの地物が届いても描かない。
    rerender({ at: new Date("2026-10-07T02:55:00Z") });
    await geojson.answer(
      0,
      Response.json({ type: "FeatureCollection", features: [{ type: "Feature", geometry: point, properties: {} }] }),
    );
    await geojson.answer(1, new HttpResponse(null, { status: 404 }));

    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error"));
    expect(result.current.dynamicWeather.disaster?.liden?.payload).toBeUndefined();
    rerender({ at: NOW });
    expect(result.current.dynamicWeather.disaster?.liden?.payload).toMatchObject({
      kind: "gridMark",
      geojson: { features: [{ geometry: point }] },
    });
  });

  it("地物で描くソースがいくつ表示されていても、それぞれのソースの地物を描く", async () => {
    const row = (validtime: string) => ({
      basetime: BASETIME,
      member: "none",
      validtime,
      elements: ["slmcs_unify", "slmcs_unifyfcst"],
    });
    onSameOrigin("GET", timesPath("nowc/targetTimes_N3.json"), () =>
      Response.json([row(BASETIME), row("20261007030500"), row("20261007031000")]),
    );
    const pointOf = (path: string) => ({
      type: "Point",
      coordinates: [path.includes("slmcs_unifyfcst/") ? 140 : 139, 35],
    });
    onSameOrigin(
      "GET",
      "/api/jma-tile/bosai/jmatile/data/nowc/:basetime/none/:validtime/surf/:element/data.geojson",
      ({ path }) =>
        Response.json({
          type: "FeatureCollection",
          features: [{ type: "Feature", geometry: pointOf(path), properties: {} }],
        }),
    );

    const { result } = render({ precipitationNowcast: true }, { precipitationNowcast: ["main", "linearRainband"] });

    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).not.toBe("loading"));
    const sources = result.current.dynamicWeather.precipitationNowcast;
    expect(sources?.linearRainbandArea?.payload).toMatchObject({
      geojson: { features: [{ geometry: pointOf("slmcs_unify/") }] },
    });
    expect(sources?.linearRainbandAreaForecast?.payload).toMatchObject({
      geojson: { features: [{ geometry: pointOf("slmcs_unifyfcst/") }] },
    });
  });

  it.each([
    {
      name: "選んだ時刻の値があれば描く",
      reply: () => windGrid("2026-10-07T12:00"),
      status: undefined,
      kinds: ["gridMark", "gridFill"],
    },
    { name: "取れなければ失敗にする", reply: failure, status: "error", kinds: [undefined, undefined] },
    {
      name: "選んだ時刻の値が無ければ空にする",
      reply: () => windGrid("2026-10-07T15:00"),
      status: "empty",
      kinds: [undefined, undefined],
    },
  ])("格子を読むソースは風の格子から値ごとの描き方で描き、$name", async ({ reply, status, kinds }) => {
    onBackend("GET", "/api/weather/wind-grid", reply);
    onSameOrigin("GET", "/api/jma-tile/*", () => Response.json([]));

    const { result } = render(
      { windVector: true, precipitationNowcast: true },
      { precipitationNowcast: PRECIPITATION_EXCEPT_MAIN },
    );

    expect(result.current.dynamicWeatherDataStatus.windVector).toBe("loading");
    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.windVector).not.toBe("loading"));
    await waitFor(() => expect(result.current.dynamicWeatherDataStatus.precipitationNowcast).not.toBe("loading"));
    expect(result.current.dynamicWeatherDataStatus).toMatchObject({ windVector: status, precipitationNowcast: status });
    expect([
      result.current.dynamicWeather.windVector?.arrow?.payload?.kind,
      result.current.dynamicWeather.precipitationNowcast?.main?.payload?.kind,
    ]).toEqual(kinds);
  });

  it("描いているコマのタイルの配信が落ちている間は、そのチップを失敗にする", async () => {
    onSameOrigin("GET", timesPath("risk/targetTimes.json"), () => Response.json(rows("rain_mesh")));
    const { result } = render({ disaster: true }, { disaster: DISASTER_NOWCAST });
    await waitFor(() => expect(result.current.dynamicWeather.disaster?.heavyRain?.payload).toBeDefined());
    registerJmaTileProtocol();
    const requestTile = protocolHandler(withJmaTileProtocol("").split("://")[0]) as (
      params: { url: string },
      abort: AbortController,
    ) => Promise<unknown>;
    const template = jmaTilePayload("rasterTile", jmaDeliveryOf("rain_mesh"), FRAME).tileUrlTemplate;
    const tile = jmaTileUrlAt(template, 5, 28, 12);
    const tilePath = new URL(tile).pathname;

    onSameOrigin("GET", tilePath, failure);
    await act(() => requestTile({ url: withJmaTileProtocol(tile) }, new AbortController()));
    expect(result.current.dynamicWeatherDataStatus.disaster).toBe("error");

    // 配信が戻れば外れる（記録はモジュールが持つので、後のテストへ残さない）。
    onSameOrigin("GET", tilePath, () => new HttpResponse(new ArrayBuffer(0)));
    await act(() => requestTile({ url: withJmaTileProtocol(tile) }, new AbortController()));
    expect(result.current.dynamicWeatherDataStatus.disaster).toBeUndefined();
  });
});

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HttpResponse } from "msw";

import { getQueryClient } from "@/lib/queryClient";
import { heldReplies, inTurn, onBackend } from "@/testing/backendServer";
import { settle } from "@/testing/settle";

import { useWeatherConditions } from "./useWeatherConditions";

// 通信は網の層でテストが決める（応答の形はbackendの契約で、ここでは画面へ渡すまでを見る）。
const WEATHER = "/api/weather";
const AMEDAS = "/api/weather/amedas";
const WARNINGS = "/api/weather/warnings";
const WBGT = "/api/weather/wbgt";
const FLOOD = "/api/weather/flood-forecast";

const TOKYO = { latitude: 35.68, longitude: 139.76 };
const YOKOHAMA = { latitude: 35.44, longitude: 139.64 };

const NO_WARNINGS = { warnings: [] };
const NO_WBGT = { reading: null };
const NO_FLOOD = { forecasts: [] };

const json = (body: unknown) => () => Response.json(body);
const failure = (detail: string) => () => Response.json({ detail }, { status: 502 });

let observations: ReturnType<typeof onBackend>;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  onBackend("GET", WEATHER, json({ precipitation_mm: 20 }));
  observations = onBackend("GET", AMEDAS, json({ temperature_c: 21 }));
  onBackend("GET", WARNINGS, json(NO_WARNINGS));
  onBackend("GET", WBGT, json(NO_WBGT));
  onBackend("GET", FLOOD, json(NO_FLOOD));
});

afterEach(() => {
  vi.useRealTimers();
});

// 取得の結果は網を通って届くので、偽にしていない時計で、取りに行った口が全部答え終えるまで待つ（届くまでの時間は
// CI の負荷で変わる。時間の早送りは取り直しの間隔だけ）。答え終える前に間隔を早送りすると、取り直しが取得中の
// ものに重なって要求を出さない。
const fetched = () => vi.waitFor(() => expect(getQueryClient().isFetching()).toBe(0));

function render(location = TOKYO, ready = true) {
  return renderHook(({ location, ready }) => useWeatherConditions(location, ready), {
    initialProps: { location, ready },
  });
}

describe("useWeatherConditions 取得の時機", () => {
  it("位置が決まるまでは取りに行かない", async () => {
    const { result } = render(TOKYO, false);
    await settle();
    expect(result.current).toMatchObject({ weather: null, amedas: null, warningBadgeItems: [] });
  });

  it("位置が決まったら、予報・実測・警報・暑さ指数・氾濫予報をその位置で取る", async () => {
    // どの口も、問い合わせた緯度・経度を値に書いて返す。
    const at = ({ query }: { query: Record<string, string> }) => `${query.latitude},${query.longitude}`;
    onBackend("GET", WEATHER, (request) => Response.json({ place: at(request) }));
    onBackend("GET", AMEDAS, (request) => Response.json({ place: at(request) }));
    onBackend("GET", WARNINGS, (request) =>
      Response.json({ warnings: [{ code: "03", name: `警報@${at(request)}`, level: "warning", additions: [] }] }),
    );
    onBackend("GET", WBGT, (request) =>
      Response.json({ reading: { level: "warning", value: 29, label: `@${at(request)}` } }),
    );
    onBackend("GET", FLOOD, (request) =>
      Response.json({
        forecasts: [{ river_code: "r1", label: `氾濫@${at(request)}`, badge_level: "warning", condition: "" }],
      }),
    );
    const { result } = render();
    const tokyo = `${TOKYO.latitude},${TOKYO.longitude}`;
    await vi.waitFor(() => {
      expect(result.current.weather).toEqual({ place: tokyo });
      expect(result.current.amedas).toEqual({ place: tokyo });
      expect(result.current.warningBadgeItems.map((item) => item.label)).toEqual([
        `警報@${tokyo}`,
        `暑さ指数@${tokyo}`,
        `氾濫@${tokyo}`,
      ]);
    });
  });

  it("位置が変わったら、緯度・経度のどちらだけの違いでも新しい位置で取り直す", async () => {
    onBackend("GET", WEATHER, ({ query }) => Response.json({ place: `${query.latitude},${query.longitude}` }));
    const { result, rerender } = render();
    await fetched();
    for (const moved of [
      { ...TOKYO, longitude: YOKOHAMA.longitude },
      { latitude: YOKOHAMA.latitude, longitude: YOKOHAMA.longitude },
    ]) {
      rerender({ location: moved, ready: true });
      await vi.waitFor(() => expect(result.current.weather).toEqual({ place: `${moved.latitude},${moved.longitude}` }));
    }
  });

  // 取り直す回数はbackendの回数制限（429）に効くので、届いた要求を数える。
  it("開いたままでも10分ごとに取り直す", async () => {
    render();
    await fetched();
    expect(observations).toHaveLength(1);
    act(() => vi.advanceTimersByTime(10 * 60 * 1000));
    await vi.waitFor(() => expect(observations).toHaveLength(2));
  });

  it("取り終えたら読み込み中を下ろし、位置を変えて取り直す間は前の位置の値のまま読み込み中にする", async () => {
    const { result, rerender } = render();
    await vi.waitFor(() => expect(result.current.weatherLoading).toBe(false));
    onBackend("GET", WEATHER, heldReplies().reply);
    rerender({ location: YOKOHAMA, ready: true });
    await vi.waitFor(() => expect(result.current.weatherLoading).toBe(true));
    expect(result.current.weather).toEqual({ precipitation_mm: 20 });
  });
});

describe("useWeatherConditions 失敗の扱い", () => {
  it("取り直しに失敗しても直前の値は残し、失敗の文言を添える。次に取れたら文言は消える", async () => {
    onBackend(
      "GET",
      WEATHER,
      inTurn(
        Response.json({ precipitation_mm: 20 }),
        Response.json({ detail: "予報を取得できませんでした" }, { status: 502 }),
        Response.json({ precipitation_mm: 20 }),
      ),
    );
    const { result } = render();
    await vi.waitFor(() => expect(result.current.weather).toEqual({ precipitation_mm: 20 }));

    act(() => vi.advanceTimersByTime(10 * 60 * 1000));
    await vi.waitFor(() => expect(result.current.weatherError).toBe("予報を取得できませんでした"));
    expect(result.current.weather).toEqual({ precipitation_mm: 20 });

    act(() => vi.advanceTimersByTime(10 * 60 * 1000));
    await vi.waitFor(() => expect(result.current.weatherError).toBeNull());
  });
});

describe("useWeatherConditions 警報のバッジ", () => {
  it("警報・暑さ指数・氾濫予報を、この順で1つの並びにする", async () => {
    onBackend(
      "GET",
      WARNINGS,
      json({
        warnings: [
          { code: "03", name: "大雨警報", level: "warning", additions: ["土砂災害", "浸水害"] },
          { code: "10", name: "雷注意報", level: "advisory", additions: [] },
        ],
      }),
    );
    onBackend("GET", WBGT, json({ reading: { level: "warning", value: 29.04, label: "厳重警戒" } }));
    onBackend(
      "GET",
      FLOOD,
      json({
        forecasts: [{ river_code: "r1", label: "多摩川氾濫警戒", badge_level: "warning", condition: "氾濫警戒情報" }],
      }),
    );
    const { result } = render();
    await vi.waitFor(() =>
      expect(result.current.warningBadgeItems).toEqual([
        {
          id: "03",
          label: "大雨警報",
          level: "warning",
          source: "jma",
          title: "付随事項: 土砂災害・浸水害",
        },
        { id: "10", label: "雷注意報", level: "advisory", source: "jma" },
        { id: "wbgt", label: "暑さ指数厳重警戒", level: "warning", source: "wbgt", title: "暑さ指数 29.0" },
        { id: "flood-r1", label: "多摩川氾濫警戒", level: "warning", source: "flood", title: "氾濫警戒情報" },
      ]),
    );
  });

  it("取得に失敗した出所はバッジを出さず、失敗として名前と理由を渡す（「警告なし」と読ませない）", async () => {
    onBackend("GET", WARNINGS, json({ warnings: [{ code: "03", name: "大雨警報", level: "warning", additions: [] }] }));
    const { result } = render();
    await fetched();
    await vi.waitFor(() => expect(result.current.warningBadgeItems).toHaveLength(1));

    onBackend("GET", WARNINGS, failure("取得できませんでした。"));
    onBackend("GET", FLOOD, () => HttpResponse.error());
    act(() => vi.advanceTimersByTime(10 * 60 * 1000));
    await vi.waitFor(() =>
      expect(result.current.warningFetchFailures).toMatchObject([
        {
          id: "jma",
          label: "警報・注意報",
          detail: "取得できませんでした。",
          effect: "出ていてもバッジは表示されません。",
        },
        { id: "flood", label: "河川氾濫予報", detail: "河川氾濫予報の取得に失敗しました[通信エラー]" },
      ]),
    );
    expect(result.current.warningBadgeItems).toEqual([]);
  });
});

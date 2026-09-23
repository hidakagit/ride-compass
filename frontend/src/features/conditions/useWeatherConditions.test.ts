import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWeatherConditions } from "./useWeatherConditions";

// 通信はテストが決める（応答の形はbackendの契約で、ここでは画面へ渡すまでを見る）。
const api = vi.hoisted(() => ({
  getCurrentWeather: vi.fn(),
  getAmedasObservation: vi.fn(),
  getWeatherWarnings: vi.fn(),
  getWbgtStatus: vi.fn(),
  getFloodForecasts: vi.fn(),
}));
vi.mock("@/services/weatherApi", () => api);

const TOKYO = { latitude: 35.68, longitude: 139.76 };
const YOKOHAMA = { latitude: 35.44, longitude: 139.64 };

const NO_WARNINGS = { warnings: [] };
const NO_WBGT = { level: null, value: null, label: null };
const NO_FLOOD = { forecasts: [] };

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  api.getCurrentWeather.mockResolvedValue({ temperature_c: 20 });
  api.getAmedasObservation.mockResolvedValue({ temperature_c: 21 });
  api.getWeatherWarnings.mockResolvedValue(NO_WARNINGS);
  api.getWbgtStatus.mockResolvedValue(NO_WBGT);
  api.getFloodForecasts.mockResolvedValue(NO_FLOOD);
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

/** 取りに行く・応答を反映する、の非同期の段を最後まで進める（時間の早送りは取り直しの間隔だけ）。 */
async function settle() {
  await act(async () => {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

function render(location = TOKYO, ready = true) {
  return renderHook(({ location, ready }) => useWeatherConditions(location, ready), {
    initialProps: { location, ready },
  });
}

describe("useWeatherConditions 取得の時機", () => {
  it("位置が決まるまでは取りに行かない", async () => {
    render(TOKYO, false);
    await settle();
    expect(api.getCurrentWeather).not.toHaveBeenCalled();
    expect(api.getWeatherWarnings).not.toHaveBeenCalled();
  });

  it("位置が決まったら、予報・実測・警報・暑さ指数・氾濫予報をその位置で取る", async () => {
    const { result } = render();
    await settle();
    expect(result.current.weather).toEqual({ temperature_c: 20 });
    for (const fetcher of Object.values(api)) expect(fetcher).toHaveBeenCalledWith(TOKYO);
    expect(result.current.amedas).toEqual({ temperature_c: 21 });
  });

  it("位置が変わったら、新しい位置で取り直す", async () => {
    const { rerender } = render();
    await settle();
    expect(api.getCurrentWeather).toHaveBeenCalledTimes(1);
    rerender({ location: YOKOHAMA, ready: true });
    await settle();
    expect(api.getCurrentWeather).toHaveBeenLastCalledWith(YOKOHAMA);
  });

  it("開いたままでも10分ごとに取り直す", async () => {
    render();
    await settle();
    expect(api.getAmedasObservation).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(10 * 60 * 1000));
    expect(api.getAmedasObservation).toHaveBeenCalledTimes(2);
  });

  it("後から投げた問い合わせの結果だけを反映する（先に投げた遅い応答で上書きしない）", async () => {
    let resolveSlow: (value: unknown) => void = () => {};
    api.getCurrentWeather.mockReturnValueOnce(new Promise((resolve) => (resolveSlow = resolve)));
    api.getCurrentWeather.mockResolvedValueOnce({ temperature_c: 25 });
    const { result, rerender } = render();
    await settle();
    expect(api.getCurrentWeather).toHaveBeenCalledTimes(1);
    rerender({ location: YOKOHAMA, ready: true });
    await settle();
    expect(result.current.weather).toEqual({ temperature_c: 25 });
    await act(async () => resolveSlow({ temperature_c: 10 }));
    expect(result.current.weather).toEqual({ temperature_c: 25 });
  });

  it("先に投げた問い合わせが後から失敗しても、失敗の文言を出さない（反映するのは最後の問い合わせだけ）", async () => {
    let rejectSlow: (reason: unknown) => void = () => {};
    api.getCurrentWeather.mockReturnValueOnce(new Promise((_, reject) => (rejectSlow = reject)));
    api.getCurrentWeather.mockResolvedValueOnce({ temperature_c: 25 });
    const { result, rerender } = render();
    await settle();
    rerender({ location: YOKOHAMA, ready: true });
    await settle();
    await act(async () => rejectSlow(new Error("遅れて失敗")));
    expect(result.current.weatherError).toBeNull();
    expect(result.current.weather).toEqual({ temperature_c: 25 });
  });

  it("先に投げた問い合わせが終わっても、最後の問い合わせを待つ間は読み込み中のまま", async () => {
    let resolveSlow: (value: unknown) => void = () => {};
    api.getCurrentWeather.mockReturnValueOnce(new Promise((resolve) => (resolveSlow = resolve)));
    api.getCurrentWeather.mockReturnValueOnce(new Promise(() => {}));
    const { result, rerender } = render();
    await settle();
    rerender({ location: YOKOHAMA, ready: true });
    await settle();
    await act(async () => resolveSlow({ temperature_c: 10 }));
    expect(result.current.weatherLoading).toBe(true);
    expect(result.current.weather).toBeNull();
  });

  it("画面を閉じた後は、取り直しも応答の反映もしない", async () => {
    const { unmount } = render();
    await settle();
    expect(api.getCurrentWeather).toHaveBeenCalledTimes(1);
    unmount();
    act(() => vi.advanceTimersByTime(10 * 60 * 1000));
    expect(api.getCurrentWeather).toHaveBeenCalledTimes(1);
  });
});

describe("useWeatherConditions 失敗の扱い", () => {
  it("取り直しに失敗しても直前の値は残し、失敗の文言を添える。次に取れたら文言は消える", async () => {
    const { result } = render();
    await settle();
    expect(result.current.weather).toEqual({ temperature_c: 20 });

    api.getCurrentWeather.mockRejectedValueOnce(new Error("予報を取得できませんでした"));
    act(() => vi.advanceTimersByTime(10 * 60 * 1000));
    await settle();
    expect(result.current.weatherError).toBe("予報を取得できませんでした");
    expect(result.current.weather).toEqual({ temperature_c: 20 });

    act(() => vi.advanceTimersByTime(10 * 60 * 1000));
    await settle();
    expect(result.current.weatherError).toBeNull();
  });

  it("Error以外で失敗したら、決まった文言にする", async () => {
    api.getAmedasObservation.mockRejectedValue("boom");
    const { result } = render();
    await settle();
    expect(result.current.amedasError).toBe("不明なエラーが発生しました");
  });

  it("取っている間は読み込み中の印を立て、終われば下ろす", async () => {
    let resolve: (value: unknown) => void = () => {};
    api.getCurrentWeather.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    const { result } = render();
    await settle();
    expect(result.current.weatherLoading).toBe(true);
    await act(async () => resolve({ temperature_c: 20 }));
    expect(result.current.weatherLoading).toBe(false);
  });
});

describe("useWeatherConditions 警報のバッジ", () => {
  it("警報・暑さ指数・氾濫予報を、この順で1つの並びにする", async () => {
    api.getWeatherWarnings.mockResolvedValue({
      warnings: [
        { code: "03", name: "大雨警報", level: "warning", additions: ["土砂災害", "浸水害"] },
        { code: "10", name: "雷注意報", level: "advisory", additions: [] },
      ],
    });
    api.getWbgtStatus.mockResolvedValue({ level: "warning", value: 29.04, label: "厳重警戒" });
    api.getFloodForecasts.mockResolvedValue({
      forecasts: [{ river_code: "r1", label: "多摩川氾濫警戒", badge_level: "warning", condition: "氾濫警戒情報" }],
    });
    const { result } = render();
    await settle();
    expect(result.current.warningBadgeItems).toEqual([
      {
        id: "03",
        label: "大雨警報",
        level: "warning",
        source: "jma",
        title: "付随事項: 土砂災害・浸水害 / 取得できない場合は警報が出ていてもバッジが表示されないことがあります",
      },
      {
        id: "10",
        label: "雷注意報",
        level: "advisory",
        source: "jma",
        title: "取得できない場合は警報が出ていてもバッジが表示されないことがあります",
      },
      {
        id: "wbgt",
        label: "暑さ指数厳重警戒",
        level: "warning",
        source: "wbgt",
        title: "暑さ指数 29.0 / 取得できない場合は警戒レベルに関わらずバッジが表示されないことがあります",
      },
      {
        id: "flood-r1",
        label: "多摩川氾濫警戒",
        level: "warning",
        source: "flood",
        title: "氾濫警戒情報 / 取得できない場合は氾濫予報が出ていてもバッジが表示されないことがあります",
      },
    ]);
  });

  it("暑さ指数の段階の呼び名が無ければ、「暑さ指数」とだけ出す", async () => {
    api.getWbgtStatus.mockResolvedValue({ level: "advisory", value: 25, label: null });
    const { result } = render();
    await settle();
    expect(result.current.warningBadgeItems.map((item) => item.label)).toEqual(["暑さ指数"]);
  });

  it("暑さ指数は、段階と値の両方があるときだけ出す", async () => {
    api.getWbgtStatus.mockResolvedValue({ level: "warning", value: null, label: "厳重警戒" });
    const { result } = render();
    await settle();
    expect(api.getWbgtStatus).toHaveBeenCalled();
    expect(result.current.warningBadgeItems).toEqual([]);
  });

  it("取得に失敗した出所はバッジを出さず、失敗として名前と理由を渡す（「警告なし」と読ませない）", async () => {
    api.getWeatherWarnings.mockResolvedValue({
      warnings: [{ code: "03", name: "大雨警報", level: "warning", additions: [] }],
    });
    const { result } = render();
    await settle();
    expect(result.current.warningBadgeItems).toHaveLength(1);

    api.getWeatherWarnings.mockRejectedValue(new Error("警報を取得できませんでした"));
    api.getFloodForecasts.mockRejectedValue(new Error("氾濫予報を取得できませんでした"));
    act(() => vi.advanceTimersByTime(10 * 60 * 1000));
    await settle();
    expect(result.current.warningBadgeItems).toEqual([]);
    expect(result.current.warningFetchFailures).toEqual([
      { id: "jma", label: "警報・注意報", detail: "警報を取得できませんでした" },
      { id: "flood", label: "河川氾濫予報", detail: "氾濫予報を取得できませんでした" },
    ]);
  });
});

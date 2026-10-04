// @vitest-environment node
/**
 * `services/weatherApi.ts`——気象（天候・アメダス・警報・暑さ指数・河川氾濫・風の格子・気象庁タイルの在否）をbackendから
 * 取る口。入口は公開の関数、差し替えるのは網（msw）で、確かめるのは送った要求と戻り値。
 *
 * ここで見ないもの:
 * - 口ごとのパスと応答の型の組 → OpenAPIの生成物から型で決まり、取り違えると型検査が落ちる
 * - 失敗を投げること・失敗の文言の組み立て（口ごとの主語は宣言）・通信の失敗とタイムアウトの包み直し → `lib/apiClient.test.ts`
 * - 地点を問い合わせるほかの口（アメダス・警報・暑さ指数・河川氾濫）と気象庁タイルの在否 → 地点を項目へ載せる形は天候と
 *   同じで、要求は取った値を使う側のテストが網の層で通す
 * - 取った値を画面の状態へ載せること → `features/conditions/useWeatherConditions.test.ts`・
 *   `features/map/useWeatherGrid.test.ts`・`features/map/useJmaTileIndex.test.ts`
 */
import { describe, expect, it } from "vitest";

import { onBackend } from "@/testing/backendServer";

import { getCurrentWeather, getWindGrid, getWindGridDetail } from "./weatherApi";

const POINT = { latitude: 35.68, longitude: 139.76 };

/** 時刻の列を1本だけ持つ、backendの風の格子の応答。 */
const GRID = {
  times: ["2026-10-01T09:00:00+09:00", "2026-10-01T10:00:00+09:00"],
  points: [
    { latitude: 35.5, longitude: 139.5, speeds: [1, 2], directions: [90, 180] },
    { latitude: 35.6, longitude: 139.7, speeds: [3, 4], directions: [0, 270] },
  ],
};

describe("地点を問い合わせる口", () => {
  it("地点の緯度・経度をそれぞれの項目へ載せ、届いた本文を返す", async () => {
    const weather = { precipitation_mm: 0.5 };
    const sent = onBackend("GET", "/api/weather", () => Response.json(weather));

    await expect(getCurrentWeather(POINT)).resolves.toEqual(weather);
    expect(sent).toEqual([
      { method: "GET", path: "/api/weather", query: { latitude: "35.68", longitude: "139.76" }, body: undefined },
    ]);
  });
});

describe("風の格子", () => {
  it("対象範囲の格子は、応答に1本だけある時刻の列を各点へ持たせて返す", async () => {
    onBackend("GET", "/api/weather/wind-grid", () => Response.json(GRID));

    expect(await getWindGrid()).toEqual(GRID.points.map((point) => ({ ...point, times: GRID.times })));
  });

  it("表示範囲の格子は、範囲の四辺と間隔を問い合わせへ載せ、時刻の列を各点へ持たせて返す", async () => {
    const sent = onBackend("GET", "/api/weather/wind-grid-detail", () => Response.json(GRID));

    const points = await getWindGridDetail({ minLon: 139.1, minLat: 35.2, maxLon: 139.9, maxLat: 35.8 }, 0.05);

    expect(points).toEqual(GRID.points.map((point) => ({ ...point, times: GRID.times })));
    expect(sent.map(({ path, query }) => ({ path, query }))).toEqual([
      {
        path: "/api/weather/wind-grid-detail",
        query: { min_lon: "139.1", min_lat: "35.2", max_lon: "139.9", max_lat: "35.8", spacing_deg: "0.05" },
      },
    ]);
  });
});

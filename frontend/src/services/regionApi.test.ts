// @vitest-environment node
/**
 * `services/regionApi.ts`——地域のデータの口。地図ライブラリへ渡すタイルのURL（世代つき）と、backendを呼ぶ口
 * （押した道の内訳・専用配信の軸の道ごとの値）。入口は公開の関数。差し替えるのは網（`fetch`）とタイルのオリジンの
 * 読み取り口（`lib/tileBaseUrl.ts: tileBaseUrl`）で、確かめるのは戻り値・投げるもの・送った要求。
 *
 * タイルの世代はモジュールが持つ状態なので、世代を扱うテストはモジュールを読み直して「まだ届いていない」から始める。
 *
 * ここで見ないもの:
 * - タイルのオリジンの決め方 → `lib/tileBaseUrl.test.ts`
 * - パスの`{名前}`の埋め方 → `lib/apiPath.ts`を通る全URLが同じで、ここでは結果のURLだけを見る
 * - 失敗の文言の組み立て・通信の失敗とタイムアウトの包み直し → `lib/apiClient.test.ts`
 * - 世代が揃うのを待ってから地図を描くこと → `features/map/useTileVersionsReady.ts`を使う側のテスト
 * - 内訳・道ごとの値を画面へ出すこと → `features/map/MapView/RoadInspectorPopup.test.tsx`・
 *   `features/map/useDedicatedWayValues.test.ts`
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { stubBackend } from "@/testing/backendFetch";
import regionTileConfig from "@/types/generated/region-tile-config.json";

vi.mock("@/lib/tileBaseUrl", () => ({ tileBaseUrl: () => "https://tiles.example" }));

type RegionApi = typeof import("./regionApi");

/** 世代がまだ届いていない状態のモジュール。 */
async function freshRegionApi(): Promise<RegionApi> {
  vi.resetModules();
  return import("./regionApi");
}

/** 配信される全系統へ、系統名から作った世代を入れた辞書。 */
function allVersions(): Record<string, string> {
  const kinds = regionTileConfig.tile_version_kinds;
  expect(kinds.length).toBeGreaterThan(0);
  return Object.fromEntries(kinds.map((kind) => [kind, `${kind}-v1`]));
}

const TILE_URLS = [
  ["roadSurfaceTileUrl", "road_surface", "/api/region/road-surface-tiles/{z}/{x}/{y}.pbf"],
  ["accidentTileUrl", "accident", "/api/region/accident-tiles/{z}/{x}/{y}.pbf"],
  ["poiTileUrl", "poi", "/api/region/poi-tiles/{z}/{x}/{y}.pbf"],
] as const;

describe("タイルの世代とURL", () => {
  it("世代が届く前は「揃っていない」と答え、世代を要るURLは組み立てずに投げる", async () => {
    const api = await freshRegionApi();

    expect(api.hasTileVersions()).toBe(false);
    for (const [name] of TILE_URLS) {
      expect(() => api[name](), name).toThrow(Error);
    }
  });

  it.each(TILE_URLS)(
    "%sは、オリジン・地図ライブラリが埋める{z}/{x}/{y}・その系統の世代を持つ",
    async (name, kind, path) => {
      const api = await freshRegionApi();
      api.setTileVersions(allVersions());

      expect(api.hasTileVersions()).toBe(true);
      expect(api[name]()).toBe(`https://tiles.example${path}?v=${kind}-v1`);
    },
  );

  it("系統が1つでも欠けているか空なら「揃っていない」で、欠けた系統のURLだけを組み立てない", async () => {
    const api = await freshRegionApi();
    const withoutRoad = Object.fromEntries(Object.entries(allVersions()).filter(([kind]) => kind !== "road_surface"));

    api.setTileVersions(withoutRoad);
    expect(api.hasTileVersions()).toBe(false);
    expect(() => api.roadSurfaceTileUrl()).toThrow(Error);
    expect(api.accidentTileUrl()).toContain("?v=accident-v1");

    api.setTileVersions({ ...allVersions(), road_surface: "" });
    expect(api.hasTileVersions()).toBe(false);

    api.setTileVersions({});
    expect(api.hasTileVersions()).toBe(false);
  });

  it("土地被覆のタイルは実行時の世代を待たず、生成物の世代で組み立てる", async () => {
    const api = await freshRegionApi();

    expect(api.landcoverTileUrl()).toBe(
      `https://tiles.example/api/region/landcover-tiles/{z}/{x}/{y}.png?v=${regionTileConfig.landcover.tile_version}`,
    );
  });

  it("世代が入れ替わるたびに購読者へ知らせ、購読をやめた者には知らせない", async () => {
    const api = await freshRegionApi();
    const kept = vi.fn();
    const dropped = vi.fn();
    api.subscribeTileVersions(kept);
    const unsubscribe = api.subscribeTileVersions(dropped);

    api.setTileVersions(allVersions());
    unsubscribe();
    api.setTileVersions({});

    expect(kept).toHaveBeenCalledTimes(2);
    expect(dropped).toHaveBeenCalledTimes(1);
  });
});

describe("押した道の内訳（fetchAxisInspector）", () => {
  let api: RegionApi;
  beforeEach(async () => {
    api = await freshRegionApi();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("道だけを渡せば、道のidだけを送る（重み・地物・走行の条件はbackendの既定に任せる）", async () => {
    const result = { composite_difficulty: 42 };
    const sent = stubBackend(() => Response.json(result));

    await expect(api.fetchAxisInspector(123, null, null, null)).resolves.toEqual(result);

    expect(sent.map(({ method, path, body }) => ({ method, path, body }))).toEqual([
      { method: "POST", path: "/api/region/axis-inspector", body: { osm_way_id: 123 } },
    ]);
  });

  it("押した地物・重み・タイルと走行の条件を、backendの項目名で送る", async () => {
    const sent = stubBackend(() => Response.json({}));

    await api.fetchAxisInspector(
      123,
      "123:4",
      { z: 15, x: 29100, y: 12900, bearingDeg: 270, at: new Date("2026-10-01T00:30:00Z"), speedKmh: 22 },
      { wind: 2, slope: 0 },
    );

    expect(sent[0].body).toEqual({
      osm_way_id: 123,
      feature_key: "123:4",
      route_preference: { wind: 2, slope: 0 },
      z: 15,
      x: 29100,
      y: 12900,
      bearing_deg: 270,
      at: "2026-10-01T00:30:00.000Z",
      speed_kmh: 22,
    });
  });

  it("時刻・速度を持たない条件では、その項目を送らない", async () => {
    const sent = stubBackend(() => Response.json({}));

    await api.fetchAxisInspector(123, null, { z: 15, x: 1, y: 2, bearingDeg: 0 });

    expect(sent[0].body).toEqual({ osm_way_id: 123, z: 15, x: 1, y: 2, bearing_deg: 0 });
  });

  it("backendが評価を返さなければnullを返し、失敗したら内訳の取得の失敗として投げる", async () => {
    stubBackend(() => Response.json(null));
    await expect(api.fetchAxisInspector(123)).resolves.toBeNull();

    stubBackend(() => new Response(null, { status: 500 }));
    await expect(api.fetchAxisInspector(123)).rejects.toThrow("内訳の取得に失敗しました");

    stubBackend(() => new Response("{not json", { status: 200 }));
    await expect(api.fetchAxisInspector(123)).rejects.toThrow("内訳の取得に失敗しました");
  });
});

describe("専用配信の軸の道ごとの値（fetchDynamicWayValues）", () => {
  let api: RegionApi;
  beforeEach(async () => {
    api = await freshRegionApi();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("軸とタイルをパスへ、方位・時刻・速度を問い合わせへ載せ、道ごとの値を返す", async () => {
    const sent = stubBackend(() => Response.json({ "101": 3.5, "102": -1 }));

    const result = await api.fetchDynamicWayValues(
      "axis_a",
      15,
      29100,
      12900,
      90,
      new Date("2026-10-01T00:00:00Z"),
      25,
    );

    expect(result).toEqual({ values: { "101": 3.5, "102": -1 }, error: false });
    expect(sent.map(({ method, path, query }) => ({ method, path, query }))).toEqual([
      {
        method: "GET",
        path: "/api/region/dynamic-way-values/axis_a/15/29100/12900",
        query: { bearing_deg: "90", at: "2026-10-01T00:00:00.000Z", speed_kmh: "25" },
      },
    ]);
  });

  it("渡さなかった条件と、有限でない速度は問い合わせに載せない", async () => {
    const sent = stubBackend(() => Response.json({}));

    await api.fetchDynamicWayValues("axis_a", 15, 1, 2, undefined);
    await api.fetchDynamicWayValues("axis_a", 15, 1, 2, 0, undefined, Number.NaN);
    await api.fetchDynamicWayValues("axis_a", 15, 1, 2, 0, undefined, Number.POSITIVE_INFINITY);

    expect(sent.map(({ query }) => query)).toEqual([{}, { bearing_deg: "0" }, { bearing_deg: "0" }]);
  });

  it("本当に道が無い（空の応答）なら失敗にしない", async () => {
    stubBackend(() => Response.json({}));

    await expect(api.fetchDynamicWayValues("axis_a", 15, 1, 2, 0)).resolves.toEqual({ values: {}, error: false });
  });

  it("失敗は投げずに、空の値と失敗の印で返す（色分けの失敗で道路や他のレイヤーを止めない）", async () => {
    stubBackend(() => new Response(null, { status: 500 }));

    await expect(api.fetchDynamicWayValues("axis_a", 15, 1, 2, 0)).resolves.toEqual({ values: {}, error: true });
  });
});

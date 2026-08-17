import { afterEach, describe, expect, it, vi } from "vitest";
import regionTileConfig from "@/types/generated/region-tile-config.json";
import {
  ACCIDENT_TILE_SOURCE_LAYER,
  ROAD_TILE_SOURCE_LAYER,
  STOP_POI_SOURCE_LAYER,
} from "@/components/Map/MapView";
import {
  ROAD_TILE_MAX_ZOOM,
  ROAD_TILE_MIN_ZOOM,
  accidentTileUrl,
  fetchTrafficStressBreakdown,
  poiTileUrl,
  refreshBasemapCache,
  roadSurfaceTileUrl,
} from "./regionApi";

// ROAD_SURFACE_TILE_VERSION/POI_TILE_VERSION自体はregionApi.tsからexportされていないため、
// 各tileUrl()の?v=から実際に使われている値を取り出して比較する
// （2重に手書き定数を持たず、実際の挙動を検証対象にする）。
function tileVersionFromUrl(url: string): string {
  return new URL(url).searchParams.get("v") ?? "";
}

describe("regionApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("ROAD_TILE_MIN_ZOOM/MAX_ZOOMはバックエンドのregion.pyと合わせた値", () => {
    expect(ROAD_TILE_MIN_ZOOM).toBe(12);
    expect(ROAD_TILE_MAX_ZOOM).toBe(15);
  });

  it("roadSurfaceTileUrlはwindow.location.originとタイル世代クエリを使ったURLテンプレートを返す", () => {
    // ?v=はタイルへ焼き込むプロパティが変わった世代の切替でブラウザキャッシュをバストする
    expect(roadSurfaceTileUrl()).toBe(`${window.location.origin}/api/region/road-surface-tiles/{z}/{x}/{y}.pbf?v=10`);
  });

  // region-tile-config.jsonはbackendのvector_tile.ROAD_SURFACE_LAYER_NAME /
  // region_service.ROAD_SURFACE_TILE_VERSIONからbackend/scripts/export_openapi.pyが生成する
  // （CIのapi-contractジョブがドリフト検知、改善計画T19）。片側だけ値を変えて再生成・
  // コミットし忘れた状態をCIで検出する。
  it("路面ベクタタイルのレイヤー名・世代がbackend生成物（region-tile-config.json）と一致する", () => {
    expect(ROAD_TILE_SOURCE_LAYER).toBe(regionTileConfig.road_surface.layer_name);
    expect(tileVersionFromUrl(roadSurfaceTileUrl())).toBe(regionTileConfig.road_surface.tile_version);
  });

  it("poiTileUrlはwindow.location.originとタイル世代クエリを使ったURLテンプレートを返す", () => {
    expect(poiTileUrl()).toBe(`${window.location.origin}/api/region/poi-tiles/{z}/{x}/{y}.pbf?v=2`);
  });

  // 停止要因POIタイル（改善計画T54）も同じドリフト検知の対象にする。交差点密度
  // （intersection）レイヤーは地図の独立可視化レイヤーとしては提供しない判断（T96）で
  // フロントから参照が無くなっていたため、バックエンド側の配信自体もT97で撤去済み。
  it("POIベクタタイルのレイヤー名・世代がbackend生成物と一致する", () => {
    expect(STOP_POI_SOURCE_LAYER).toBe(regionTileConfig.poi.stop_poi_layer_name);
    expect(tileVersionFromUrl(poiTileUrl())).toBe(regionTileConfig.poi.tile_version);
  });

  // 外部静的データソース T50（警察庁事故データ）のMVTレイヤー名・世代も同じドリフト検知
  // の仕組みに乗せる（region-tile-config.jsonのaccidentキー、改善計画T19と同型）。
  it("事故ベクタタイルのレイヤー名・世代がbackend生成物（region-tile-config.json）と一致する", () => {
    expect(ACCIDENT_TILE_SOURCE_LAYER).toBe(regionTileConfig.accident.layer_name);
    expect(tileVersionFromUrl(accidentTileUrl())).toBe(regionTileConfig.accident.tile_version);
  });

  it("accidentTileUrlはwindow.location.originとタイル世代クエリを使ったURLテンプレートを返す", () => {
    expect(accidentTileUrl()).toBe(`${window.location.origin}/api/region/accident-tiles/{z}/{x}/{y}.pbf?v=1`);
  });

  describe("fetchTrafficStressBreakdown", () => {
    it("osm_way_idをJSONボディに含めてPOSTし、JSONをそのまま返す", async () => {
      const breakdown = {
        base: 4,
        cycleway_adjustment: 0,
        maxspeed_adjustment: 1,
        lanes_adjustment: 0,
        designation_adjustment: 0,
        motor_vehicle_no_override: false,
        level: 4,
      };
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => breakdown,
      });
      vi.stubGlobal("fetch", fetchMock);

      const result = await fetchTrafficStressBreakdown(12345);

      const [url, options] = fetchMock.mock.calls[0];
      expect(String(url)).toContain("/api/region/traffic-stress-breakdown");
      expect(options.method).toBe("POST");
      expect(JSON.parse(options.body as string)).toEqual({ osm_way_id: 12345, traffic_stress_recipe: null });
      expect(result).toEqual(breakdown);
    });

    it("該当wayが無い場合(null)もそのまま返す", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({ ok: true, status: 200, headers: new Headers(), json: async () => null }),
      );

      await expect(fetchTrafficStressBreakdown(12345)).resolves.toBeNull();
    });

    it("fetchがok:falseの場合は例外を投げる", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: false,
          status: 429,
          headers: new Headers(),
          json: async () => ({ detail: "リクエストが多すぎます。" }),
        }),
      );

      await expect(fetchTrafficStressBreakdown(12345)).rejects.toThrow(/リクエストが多すぎます/);
    });
  });

  describe("refreshBasemapCache", () => {
    it("POSTで/api/basemap/refreshを含むURLへ呼ばれる", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
      });
      vi.stubGlobal("fetch", fetchMock);

      await refreshBasemapCache();

      const [url, options] = fetchMock.mock.calls[0];
      expect(String(url)).toContain("/api/basemap/refresh");
      expect(options.method).toBe("POST");
    });

    it("fetchがok:falseの場合は例外を投げる(以前は無反応に見えるサイレント失敗だった)", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: false,
          status: 502,
          headers: new Headers(),
        }),
      );

      await expect(refreshBasemapCache()).rejects.toThrow(/502/);
    });

    it("fetch自体が例外を投げる場合もエラーとして伝播する", async () => {
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));

      await expect(refreshBasemapCache()).rejects.toThrow("network error");
    });
  });
});

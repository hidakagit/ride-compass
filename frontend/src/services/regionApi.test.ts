import { afterEach, describe, expect, it, vi } from "vitest";
import regionTileConfig from "@/types/generated/region-tile-config.json";
import { ROAD_TILE_SOURCE_LAYER } from "@/components/Map/MapView";
import { ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM, refreshBasemapCache, roadSurfaceTileUrl } from "./regionApi";

// ROAD_SURFACE_TILE_VERSION自体はregionApi.tsからexportされていないため、
// roadSurfaceTileUrl()の?v=から実際に使われている値を取り出して比較する
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
    expect(roadSurfaceTileUrl()).toBe(`${window.location.origin}/api/region/road-surface-tiles/{z}/{x}/{y}.pbf?v=3`);
  });

  // region-tile-config.jsonはbackendのvector_tile.ROAD_SURFACE_LAYER_NAME /
  // region_service.ROAD_SURFACE_TILE_VERSIONからbackend/scripts/export_openapi.pyが生成する
  // （CIのapi-contractジョブがドリフト検知、改善計画T19）。片側だけ値を変えて再生成・
  // コミットし忘れた状態をCIで検出する。
  it("路面ベクタタイルのレイヤー名・世代がbackend生成物（region-tile-config.json）と一致する", () => {
    expect(ROAD_TILE_SOURCE_LAYER).toBe(regionTileConfig.layer_name);
    expect(tileVersionFromUrl(roadSurfaceTileUrl())).toBe(regionTileConfig.tile_version);
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

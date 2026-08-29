import { afterEach, describe, expect, it, vi } from "vitest";
import { debugLog } from "@/lib/debugLog";
import regionTileConfig from "@/types/generated/region-tile-config.json";

// 改善計画T328回帰テスト: refreshBasemapCacheが!response.ok時のthrowを自分のcatchで
// 再捕捉し、「失敗 (HTTP xxx)」の直後に「失敗 (通信エラー)」と誤って二重ログしていた
// 不具合の検証に、debugLogの呼び出し回数・ラベルを直接アサートする必要があるためモックする。
vi.mock("@/lib/debugLog", () => ({ debugLog: vi.fn() }));
import {
  ACCIDENT_TILE_SOURCE_LAYER,
  ROAD_TILE_SOURCE_LAYER,
  STOP_POI_SOURCE_LAYER,
} from "@/components/Map/MapView";
import {
  ROAD_TILE_MAX_ZOOM,
  ROAD_TILE_MIN_ZOOM,
  accidentTileUrl,
  fetchAxisInspector,
  fetchDynamicWayValues,
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
    expect(roadSurfaceTileUrl()).toBe(`${window.location.origin}/api/region/road-surface-tiles/{z}/{x}/{y}.pbf?v=17`);
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
    expect(poiTileUrl()).toBe(`${window.location.origin}/api/region/poi-tiles/{z}/{x}/{y}.pbf?v=3`);
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

  describe("fetchAxisInspector", () => {
    it("osm_way_idをJSONボディに含めてPOSTし、JSONをそのまま返す", async () => {
      const result_ = {
        highway: "residential",
        tags: {},
        is_designated: false,
        axes: [{ axis_id: "car_stress", difficulty: 25.0, weight: 0.2, available: true }],
        composite_difficulty: 25.0,
        covered_weight_fraction: 1.0,
      };
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => result_,
      });
      vi.stubGlobal("fetch", fetchMock);

      const result = await fetchAxisInspector(12345);

      const [url, options] = fetchMock.mock.calls[0];
      expect(String(url)).toContain("/api/region/axis-inspector");
      expect(options.method).toBe("POST");
      expect(JSON.parse(options.body as string)).toEqual({ osm_way_id: 12345 });
      expect(result).toEqual(result_);
    });

    it("該当wayが無い場合(null)もそのまま返す", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({ ok: true, status: 200, headers: new Headers(), json: async () => null }),
      );

      await expect(fetchAxisInspector(12345)).resolves.toBeNull();
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

      await expect(fetchAxisInspector(12345)).rejects.toThrow(/リクエストが多すぎます/);
    });
  });

  // way_id→動的値配信層（風・勾配、改善計画T405→T414→T423）。fetchAxisInspectorと違い、
  // 失敗時は例外を投げず空オブジェクトへフォールバックする（背景の色分けレイヤーという
  // 補助的な機能のため、regionApi.tsのdocstring参照）。
  describe("fetchDynamicWayValues", () => {
    afterEach(() => {
      vi.mocked(debugLog).mockClear();
    });

    it("material_id・z/x/y・bearing_degを含むURLへGETし、{way_id: 値}のJSONをそのまま返す", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => ({ "1": 2.34, "2": -1.5 }),
      });
      vi.stubGlobal("fetch", fetchMock);

      const result = await fetchDynamicWayValues("wind", 14, 14551, 6447, 90);

      const [url, options] = fetchMock.mock.calls[0];
      // fetchAxisInspectorと同じ理由（アプリのfetch()から直接呼ぶ、MapLibreのWeb Worker
      // 経由ではない）でAPI_BASE_URL（既定値、テスト環境ではNEXT_PUBLIC_API_URL未設定時の
      // フォールバックhttp://localhost:8000）を使う。roadSurfaceTileUrl等（window.location.
      // origin経由）とは異なる点に注意。
      expect(String(url)).toBe("http://localhost:8000/api/region/dynamic-way-values/wind/14/14551/6447?bearing_deg=90");
      expect(options.method ?? "GET").toBe("GET");
      expect(result).toEqual({ "1": 2.34, "2": -1.5 });
    });

    it("material_idが変わればパスも変わる（改善計画T423、材料id駆動のエンドポイント統一）", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => ({}),
      });
      vi.stubGlobal("fetch", fetchMock);

      await fetchDynamicWayValues("gradient", 14, 14551, 6447, 90);

      const [url] = fetchMock.mock.calls[0];
      expect(String(url)).toBe("http://localhost:8000/api/region/dynamic-way-values/gradient/14/14551/6447?bearing_deg=90");
    });

    it("atを渡すとISO文字列のクエリパラメータとして付与する", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => ({}),
      });
      vi.stubGlobal("fetch", fetchMock);
      const at = new Date("2026-08-30T09:00:00.000Z");

      await fetchDynamicWayValues("wind", 14, 14551, 6447, 0, at);

      const [url] = fetchMock.mock.calls[0];
      expect(new URL(String(url)).searchParams.get("at")).toBe(at.toISOString());
    });

    it("HTTPエラー時は例外を投げず空オブジェクトを返す", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({ ok: false, status: 500, headers: new Headers() }),
      );

      await expect(fetchDynamicWayValues("wind", 14, 14551, 6447, 0)).resolves.toEqual({});
    });

    it("通信エラー時も例外を投げず空オブジェクトを返す", async () => {
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));

      await expect(fetchDynamicWayValues("wind", 14, 14551, 6447, 0)).resolves.toEqual({});
    });
  });

  describe("refreshBasemapCache", () => {
    afterEach(() => {
      vi.mocked(debugLog).mockClear();
    });

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

    // 改善計画T328回帰テスト: !response.ok時のthrowが同じtry節内のcatchで再捕捉され、
    // 正しい「失敗 (HTTP xxx)」ログの直後に誤った「失敗 (通信エラー)」が二重にログ
    // される不具合があった。debugLogがHTTPエラー時に1回だけ、正しいラベルで呼ばれる
    // ことを検証する（通信エラーラベルでは呼ばれないこと）。
    it("HTTPエラー時はdebugLogが「失敗 (HTTP xxx)」で1回だけ呼ばれ、「通信エラー」では呼ばれない", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: false,
          status: 502,
          headers: new Headers(),
        }),
      );

      await expect(refreshBasemapCache()).rejects.toThrow(/502/);

      const calls = vi.mocked(debugLog).mock.calls.filter(([category]) => category === "api:basemap-refresh");
      expect(calls).toHaveLength(2); // 「リクエスト開始」＋「失敗 (HTTP 502)」
      expect(calls.map(([, message]) => message)).toEqual(["リクエスト開始", "失敗 (HTTP 502)"]);
      expect(calls.some(([, message]) => message === "失敗 (通信エラー)")).toBe(false);
    });

    it("fetch自体が例外を投げる場合もエラーとして伝播する", async () => {
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));

      await expect(refreshBasemapCache()).rejects.toThrow("network error");
    });
  });
});

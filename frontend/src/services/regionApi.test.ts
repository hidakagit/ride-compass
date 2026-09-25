import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { debugLog } from "@/lib/debugLog";

// 成功・失敗時のdebugLogの呼び出し回数・ラベルを直接アサートするためモックする。
vi.mock("@/lib/debugLog", () => ({ debugLog: vi.fn() }));
// タイル配信オリジンは`@/lib/tileBaseUrl`が唯一の情報源で、その環境変数依存は
// `src/lib/tileBaseUrl.test.ts`が検証する。ここで固定するのは、`process.env`が
// テストファイルをまたいで共有されるため（pool: vmThreads）、別ファイルが立てた
// `NEXT_PUBLIC_TILE_BASE_URL`でこのファイルの期待値が変わらないようにするため。
vi.mock("@/lib/tileBaseUrl", () => ({ tileBaseUrl: () => "https://tiles.test" }));
import {
  accidentTileUrl,
  fetchAxisInspector,
  fetchDynamicWayValues,
  poiTileUrl,
  roadSurfaceTileUrl,
  setTileVersions,
} from "./regionApi";

// タイル世代は実行時にbackendから受け取る（setTileVersions）。
const TILE_VERSIONS = { road_surface: "7-aaaa", poi: "7-bbbb", accident: "7-cccc" } as const;

describe("regionApi", () => {
  beforeEach(() => {
    setTileVersions(TILE_VERSIONS);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("roadSurfaceTileUrlは配信オリジンとタイル世代クエリを使ったURLテンプレートを返す", () => {
    // ?v=はタイルへ焼き込むプロパティが変わった世代の切替でブラウザキャッシュをバストする
    expect(roadSurfaceTileUrl()).toBe(
      `https://tiles.test/api/region/road-surface-tiles/{z}/{x}/{y}.pbf?v=${TILE_VERSIONS.road_surface}`,
    );
  });

  it("poiTileUrlは配信オリジンとタイル世代クエリを使ったURLテンプレートを返す", () => {
    expect(poiTileUrl()).toBe(`https://tiles.test/api/region/poi-tiles/{z}/{x}/{y}.pbf?v=${TILE_VERSIONS.poi}`);
  });

  it("accidentTileUrlは配信オリジンとタイル世代クエリを使ったURLテンプレートを返す", () => {
    expect(accidentTileUrl()).toBe(
      `https://tiles.test/api/region/accident-tiles/{z}/{x}/{y}.pbf?v=${TILE_VERSIONS.accident}`,
    );
  });

  describe("fetchAxisInspector", () => {
    it("osm_way_idをJSONボディに含めてPOSTし、JSONをそのまま返す", async () => {
      const result_ = {
        highway: "residential",
        tags: {},
        axes: [{ axis_id: "axis_sample", difficulty: 25.0, weight: 0.2, available: true }],
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

    it("地図の指定が揃っていればbackendの名前でボディへ載せる", async () => {
      // 載らないと、進行方向が決まらないと算出できない軸（勾配・風）が内訳だけ
      // 「データなし」になる。鍵の綴り・日時の形はbackendのAxisInspectorRequestが正。
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => null,
      });
      vi.stubGlobal("fetch", fetchMock);

      await fetchAxisInspector(12345, "way-12345-seg0-fwd", {
        z: 14,
        x: 14551,
        y: 6447,
        bearingDeg: 90,
        at: new Date("2026-09-21T09:00:00Z"),
        speedKmh: 20,
      });

      const [, options] = fetchMock.mock.calls[0];
      expect(JSON.parse(options.body as string)).toEqual({
        osm_way_id: 12345,
        feature_key: "way-12345-seg0-fwd",
        z: 14,
        x: 14551,
        y: 6447,
        bearing_deg: 90,
        at: "2026-09-21T09:00:00.000Z",
        speed_kmh: 20,
      });
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

  // way_id→動的値配信層（風・勾配）。fetchAxisInspectorと違い、
  // 失敗時は例外を投げず空オブジェクトへフォールバックする（背景の色分けレイヤーという
  // 補助的な機能のため、regionApi.tsのdocstring参照）。
  describe("fetchDynamicWayValues", () => {
    afterEach(() => {
      vi.mocked(debugLog).mockClear();
    });

    it("axis_id・z/x/y・bearing_degを含むURLへGETし、{way_id: 値}のJSONをそのまま返す", async () => {
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
      expect(result).toEqual({ values: { "1": 2.34, "2": -1.5 }, error: false });
    });

    it("axis_idが変わればパスも変わる（軸id駆動のエンドポイント統一）", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => ({}),
      });
      vi.stubGlobal("fetch", fetchMock);

      await fetchDynamicWayValues("gradient", 14, 14551, 6447, 90);

      const [url] = fetchMock.mock.calls[0];
      expect(String(url)).toBe(
        "http://localhost:8000/api/region/dynamic-way-values/gradient/14/14551/6447?bearing_deg=90",
      );
    });

    it("speedKmhを渡すとspeed_kmhクエリパラメータとして付与する（走行速度依存の材料向け）", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => ({}),
      });
      vi.stubGlobal("fetch", fetchMock);

      await fetchDynamicWayValues("wind", 14, 14551, 6447, 90, undefined, 25);

      const [url] = fetchMock.mock.calls[0];
      expect(String(url)).toBe(
        "http://localhost:8000/api/region/dynamic-way-values/wind/14/14551/6447?bearing_deg=90&speed_kmh=25",
      );
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

    it("HTTPエラー時は例外を投げずerror:trueの空valuesを返す（本当に空のデータと区別する）", async () => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, headers: new Headers() }));

      await expect(fetchDynamicWayValues("wind", 14, 14551, 6447, 0)).resolves.toEqual({
        values: {},
        error: true,
      });
    });

    it("通信エラー時も例外を投げずerror:trueの空valuesを返す", async () => {
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));

      await expect(fetchDynamicWayValues("wind", 14, 14551, 6447, 0)).resolves.toEqual({
        values: {},
        error: true,
      });
    });
  });
});

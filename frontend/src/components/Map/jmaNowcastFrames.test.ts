// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchJmaTargetTimes } from "./jmaNowcastFrames";

// trimToCurrentAndFuture/parseValidtimeの挙動自体はprecipitationNowcast.test.ts（同じ実装の
// 再エクスポート）で検証済みのため、ここではjmaNowcastFrames.ts固有の追加分
// （fetchJmaTargetTimesのラベル付きエラーメッセージ）だけを検証する（改善計画T204）。
function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body, headers: new Headers() };
}

describe("fetchJmaTargetTimes", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("成功時はJSON配列をそのまま返す", async () => {
    const raw = [{ basetime: "1", validtime: "1" }];
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse(raw)))
    );

    const result = await fetchJmaTargetTimes("nowc_N3", "雷ナウキャスト");
    expect(result).toEqual(raw);
  });

  it("HTTPエラー時はlabelを含むエラーメッセージで例外を投げる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse(null, false, 503)))
    );

    await expect(fetchJmaTargetTimes("nowc_N3", "雷ナウキャスト")).rejects.toThrow(
      "雷ナウキャストの時刻一覧の取得に失敗しました[HTTP 503]"
    );
  });

  it("レスポンスが配列でない場合はlabelを含むエラーメッセージで例外を投げる", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ not: "an array" })))
    );

    await expect(fetchJmaTargetTimes("nowc_N3", "雷ナウキャスト")).rejects.toThrow(
      "雷ナウキャストの時刻一覧の形式が想定と異なります"
    );
  });
});

describe("jmaProxyUrl", () => {
  // タイル本体は既にtileBaseUrl()経由でbackendへ直接取りに行く。時刻一覧・GeoJSONだけが
  // 相対パス＝フロントのホスティング経由で残っており、タイルURLはその応答が返るまで
  // 確定しないため往復が初回表示のクリティカルパスに直列で乗っていた（改善計画T634）。
  const original = process.env.NEXT_PUBLIC_TILE_BASE_URL;

  afterEach(() => {
    if (original === undefined) delete process.env.NEXT_PUBLIC_TILE_BASE_URL;
    else process.env.NEXT_PUBLIC_TILE_BASE_URL = original;
    vi.resetModules();
  });

  it("配信オリジンが設定されていればタイルと同じ絶対URLになる", async () => {
    process.env.NEXT_PUBLIC_TILE_BASE_URL = "https://tiles.example.test";
    vi.resetModules();
    const { jmaProxyUrl } = await import("./jmaNowcastFrames");

    expect(jmaProxyUrl("/jmatile/data/risk/targetTimes.json")).toBe(
      "https://tiles.example.test/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json",
    );
  });

  it("末尾スラッシュは重複しない", async () => {
    process.env.NEXT_PUBLIC_TILE_BASE_URL = "https://tiles.example.test/";
    vi.resetModules();
    const { jmaProxyUrl } = await import("./jmaNowcastFrames");

    expect(jmaProxyUrl("/jmatile/data/nowc/targetTimes_N3.json")).toBe(
      "https://tiles.example.test/api/jma-tile/bosai/jmatile/data/nowc/targetTimes_N3.json",
    );
  });

  it("未設定（ローカル開発等）では相対パスのまま従来どおり動く", async () => {
    delete process.env.NEXT_PUBLIC_TILE_BASE_URL;
    vi.resetModules();
    const { jmaProxyUrl } = await import("./jmaNowcastFrames");

    // node環境ではwindowが無いためtileBaseUrl()は空文字を返す。
    expect(jmaProxyUrl("/jmatile/data/risk/targetTimes.json")).toBe(
      "/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json",
    );
  });
});

describe("fetchJmaTargetTimes（同一idの未解決フェッチを共有する）", () => {
  // rasrfは降水短時間予報と線状降水帯予測マップの2箇所が独立に取りに行く。重複排除が
  // 無いと、降水チップをONにするたび同じURLへの往復が2回発生する。
  it("同時に呼ばれた同じidは1回のfetchで済む", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => [{ basetime: "20260910T000000Z", validtime: "20260910T000000Z" }],
    });
    vi.stubGlobal("fetch", fetchMock);

    const [a, b] = await Promise.all([
      fetchJmaTargetTimes("rasrf", "降水短時間予報"),
      fetchJmaTargetTimes("rasrf", "線状降水帯予測マップ"),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(a).toEqual(b);
    vi.unstubAllGlobals();
  });

  it("解決後の呼び出しは改めて取りに行く（時刻一覧は数分で更新されるため保持しない）", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => [],
    });
    vi.stubGlobal("fetch", fetchMock);

    await fetchJmaTargetTimes("rasrf", "降水短時間予報");
    await fetchJmaTargetTimes("rasrf", "降水短時間予報");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    vi.unstubAllGlobals();
  });
});

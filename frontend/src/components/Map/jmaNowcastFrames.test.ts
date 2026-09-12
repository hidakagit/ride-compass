// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchJmaTargetTimes, jmaProxyUrl } from "./jmaNowcastFrames";

// タイル配信オリジンは`@/lib/tileBaseUrl`が唯一の情報源で、その環境変数依存は
// `src/lib/tileBaseUrl.test.ts`が検証する。ここで固定するのは、`process.env`が
// テストファイルをまたいで共有されるため（pool: vmThreads）、別ファイルが立てた
// `NEXT_PUBLIC_TILE_BASE_URL`でこのファイルの期待値が変わらないようにするため。
vi.mock("@/lib/tileBaseUrl", () => ({ tileBaseUrl: () => "" }));

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
  // 時刻一覧・GeoJSONはアプリ自身のfetch()で読むが、タイル本体と同じ配信オリジンへ向ける
  // （タイルURLは時刻一覧が返るまで確定しないため、フロントのホスティングを経由すると
  // 往復1つぶんが初回表示のクリティカルパスへ直列に乗る）。ここで見るのはオリジンの
  // 後ろのパス構造だけで、オリジンの決まり方は`src/lib/tileBaseUrl.test.ts`が持つ。
  it("配信オリジンの後ろへJMAプロキシのパスを組み立てる", () => {
    expect(jmaProxyUrl("/jmatile/data/risk/targetTimes.json")).toBe(
      "/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json",
    );
    expect(jmaProxyUrl("/jmatile/data/nowc/targetTimes_N3.json")).toBe(
      "/api/jma-tile/bosai/jmatile/data/nowc/targetTimes_N3.json",
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

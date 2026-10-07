// @vitest-environment node
import { inflateSync } from "node:zlib";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("maplibre-gl", () => import("@/testing/maplibre"));

import { mapDisplay } from "@/types/generated/mapDisplay";

import { jmaTilePayload, type JmaDelivery } from "./jmaDelivery";

type Handler = (params: { url: string }, abort: AbortController) => Promise<{ data: ArrayBuffer | Uint8Array }>;

const BASETIME = "20260924000000";
const VALIDTIME = "20260924010000";
const FRAME = { basetime: BASETIME, member: "none", validtime: VALIDTIME };
const deliveryOf = (id: string) =>
  mapDisplay.weatherElements
    .flatMap((element): readonly JmaDelivery[] => element.jmaElements)
    .find((delivery) => delivery.id === id)!;
/** そのコマのタイルのテンプレート（描画ペイロードが持つもの）と、地図ライブラリが座標を埋めたURL。 */
const TEMPLATE = jmaTilePayload("rasterTile", deliveryOf("inund"), FRAME).tileUrlTemplate;
const at = (template: string, x: number, y: number) =>
  template.replace("{z}", "5").replace("{x}", String(x)).replace("{y}", String(y));
const EMPTY_PNG_URL = at(TEMPLATE, 28, 12);
const PRESENT_PNG_URL = at(TEMPLATE, 28, 13);
const EMPTY_PBF_URL = at(jmaTilePayload("vectorTile", deliveryOf("flood"), FRAME).tileUrlTemplate, 28, 12);
const INDEX = {
  available: true,
  coverage: { min_longitude: 122, min_latitude: 24, max_longitude: 146, max_latitude: 46 },
  elements: {
    inund: { basetime: BASETIME, validtime: VALIDTIME, member: "none", zooms: { "5": [[28, 13]] } },
    flood: { basetime: BASETIME, validtime: VALIDTIME, member: "none", zooms: {} },
  },
};

// 失敗の記録とインデックスはモジュールが持つため、テストごとに読み込み直す（地図のライブラリの代役と調査用のログも、
// 読み込み直したモジュールが使うものを読む）。
async function load() {
  vi.resetModules();
  const debug = await import("@/lib/debugLog");
  debug.setDebugEnabled(true);
  const protocol = await import("./jmaTileProtocol");
  protocol.registerJmaTileProtocol();
  const { protocolHandler } = (await import("maplibre-gl")) as unknown as typeof import("@/testing/maplibre");
  const handler = protocolHandler(protocol.withJmaTileProtocol("").split("://")[0]) as Handler;
  const request = (url: string, abort = new AbortController()) =>
    handler({ url: protocol.withJmaTileProtocol(url) }, abort);
  const warnings = () => debug.getDebugLogEntries().filter((entry) => entry.level === "warn");
  return { ...protocol, request, warnings };
}

const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  // 調査用のログは、記録と同時にコンソールへも出す。
  vi.spyOn(console, "warn").mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
});

/** PNGの画素がすべて完全な透明か（IDATを展開し、各行のフィルタ種別の後ろを見る）。 */
function isFullyTransparentPng(bytes: Uint8Array): boolean {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const idat: number[] = [];
  for (let at = 8; at < bytes.length;) {
    const length = view.getUint32(at);
    const type = String.fromCharCode(...bytes.subarray(at + 4, at + 8));
    if (type === "IDAT") idat.push(...bytes.subarray(at + 8, at + 8 + length));
    at += 12 + length;
  }
  const raw = inflateSync(Uint8Array.from(idat));
  expect(raw.length).toBeGreaterThan(1);
  return raw.subarray(1).every((value) => value === 0);
}

describe("jmatile:// プロトコル", () => {
  it("空と分かっているタイルはネットワークへ出さず、完全に透明な画像を毎回新しく作って返す（ベクタは0バイト＝地物なし）", async () => {
    const { setJmaTileIndex, request } = await load();
    setJmaTileIndex(INDEX);
    const first = (await request(EMPTY_PNG_URL)).data as Uint8Array;
    const second = (await request(EMPTY_PNG_URL)).data as Uint8Array;
    expect((await request(EMPTY_PBF_URL)).data).toHaveLength(0);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(isFullyTransparentPng(first)).toBe(true);
    expect(second.buffer).not.toBe(first.buffer);
  });

  it("空と分からないタイルは実URLへ取りに行き、中身をそのまま返す", async () => {
    const { request } = await load();
    fetchMock.mockImplementation(async (url) => new Response(url === EMPTY_PNG_URL ? new Uint8Array([1, 2, 3]) : null));
    const { data } = await request(EMPTY_PNG_URL);
    expect(new Uint8Array(data as ArrayBuffer)).toEqual(new Uint8Array([1, 2, 3]));
  });
});

describe("配信の失敗の記録", () => {
  it("5xxは空タイルで代替し、そのコマのタイルのテンプレートを失敗として記録して購読者へ知らせる", async () => {
    const { request, jmaTileFailures, subscribeJmaTileFailures, warnings } = await load();
    const listener = vi.fn();
    subscribeJmaTileFailures(listener);
    fetchMock.mockResolvedValue(new Response(null, { status: 503 }));

    const { data } = await request(PRESENT_PNG_URL);
    expect(isFullyTransparentPng(data as Uint8Array)).toBe(true);
    expect(jmaTileFailures()).toEqual(new Map([["inund", TEMPLATE]]));
    expect(listener).toHaveBeenCalledTimes(1);
    expect(warnings()).toEqual([expect.objectContaining({ category: "weather" })]);
  });

  it("同じ失敗が続く間は記録の参照を変えず、知らせもしない", async () => {
    const { request, jmaTileFailures, subscribeJmaTileFailures } = await load();
    fetchMock.mockResolvedValue(new Response(null, { status: 500 }));
    await request(PRESENT_PNG_URL);
    const recorded = jmaTileFailures();
    const listener = vi.fn();
    subscribeJmaTileFailures(listener);
    await request(at(TEMPLATE, 29, 13));
    expect(jmaTileFailures()).toBe(recorded);
    expect(listener).not.toHaveBeenCalled();
  });

  it("配信元が応答すれば（404の空応答も含む）その要素の失敗を消す", async () => {
    const { request, jmaTileFailures, warnings } = await load();
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 502 }));
    await request(PRESENT_PNG_URL);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 404 }));
    await request(PRESENT_PNG_URL);
    expect(jmaTileFailures().size).toBe(0);
    expect(warnings()).toHaveLength(1);

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 502 }));
    await request(PRESENT_PNG_URL);
    fetchMock.mockResolvedValueOnce(new Response(new Uint8Array([1])));
    await request(PRESENT_PNG_URL);
    expect(jmaTileFailures().size).toBe(0);
  });

  it("到達できなければ失敗として記録して例外を返す。地図が取り消すと取りに行った要求も止め、失敗に数えない", async () => {
    const { request, jmaTileFailures } = await load();
    // 網は、渡された中断の合図で止まるまで答えない。
    fetchMock.mockImplementationOnce(
      (_url, init) =>
        new Promise((_resolve, reject) =>
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
        ),
    );
    const abort = new AbortController();
    const pending = request(PRESENT_PNG_URL, abort);
    abort.abort();
    await expect(pending).rejects.toThrow("aborted");
    expect(jmaTileFailures().size).toBe(0);

    fetchMock.mockRejectedValueOnce(new TypeError("network"));
    await expect(request(PRESENT_PNG_URL)).rejects.toThrow("network");
    expect(jmaTileFailures().get("inund")).toBe(TEMPLATE);
  });

  it("購読を外せば知らせない", async () => {
    const { request, subscribeJmaTileFailures } = await load();
    const listener = vi.fn();
    subscribeJmaTileFailures(listener)();
    fetchMock.mockResolvedValue(new Response(null, { status: 500 }));
    await request(PRESENT_PNG_URL);
    expect(listener).not.toHaveBeenCalled();
  });
});

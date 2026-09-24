// @vitest-environment node
import { inflateSync } from "node:zlib";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { addProtocol, debugLog } = vi.hoisted(() => ({ addProtocol: vi.fn(), debugLog: vi.fn() }));
vi.mock("maplibre-gl", () => ({ addProtocol }));
vi.mock("@/lib/debugLog", () => ({ debugLog }));

type Handler = (params: { url: string }, abort: AbortController) => Promise<{ data: ArrayBuffer | Uint8Array }>;

const BASETIME = "20260924000000";
const VALIDTIME = "20260924010000";
const PREFIX = `https://www.jma.go.jp/bosai/jmatile/data/risk/${BASETIME}/none/${VALIDTIME}/surf/inund/`;
const EMPTY_PNG_URL = `${PREFIX}5/28/12.png`;
const PRESENT_PNG_URL = `${PREFIX}5/28/13.png`;
const INDEX = {
  available: true,
  coverage: { min_longitude: 122, min_latitude: 24, max_longitude: 146, max_latitude: 46 },
  elements: { inund: { basetime: BASETIME, validtime: VALIDTIME, member: "none", zooms: { "5": [[28, 13]] } } },
};

// 失敗の記録とインデックスはモジュールが持つため、テストごとに読み込み直す。
async function load() {
  vi.resetModules();
  addProtocol.mockClear();
  const protocol = await import("./jmaTileProtocol");
  protocol.registerJmaTileProtocol();
  const handler = addProtocol.mock.calls[0][1] as Handler;
  const request = (url: string, abort = new AbortController()) =>
    handler({ url: protocol.withJmaTileProtocol(url) }, abort);
  return { ...protocol, request };
}

const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => {
  fetchMock.mockReset();
  debugLog.mockClear();
  vi.stubGlobal("fetch", fetchMock);
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
  it("MapLibreへの登録は1回だけ", async () => {
    const { registerJmaTileProtocol } = await load();
    registerJmaTileProtocol();
    expect(addProtocol).toHaveBeenCalledTimes(1);
    expect(addProtocol.mock.calls[0][0]).toBe("jmatile");
  });

  it("空と分かっているタイルはネットワークへ出さず、完全に透明な画像を毎回新しく作って返す", async () => {
    const { setJmaTileIndex, request } = await load();
    setJmaTileIndex(INDEX);
    const first = (await request(EMPTY_PNG_URL)).data as Uint8Array;
    const second = (await request(EMPTY_PNG_URL)).data as Uint8Array;
    expect(fetchMock).not.toHaveBeenCalled();
    expect(isFullyTransparentPng(first)).toBe(true);
    expect(second.buffer).not.toBe(first.buffer);
  });

  it("取り直したインデックスが「無し」なら、それ以後は間引かない（古いインデックスを握り続けない）", async () => {
    const { setJmaTileIndex, request } = await load();
    fetchMock.mockImplementation(async () => new Response(new Uint8Array([1])));
    setJmaTileIndex(INDEX);
    await request(EMPTY_PNG_URL);
    expect(fetchMock).not.toHaveBeenCalled();
    setJmaTileIndex({ available: false });
    await request(EMPTY_PNG_URL);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("空と分かっているベクタタイルは0バイト（地物なし）", async () => {
    const { setJmaTileIndex, request } = await load();
    setJmaTileIndex(INDEX);
    expect((await request(EMPTY_PNG_URL.replace(".png", ".pbf"))).data).toHaveLength(0);
  });

  it("それ以外は実URLへ取りに行き、中身をそのまま返す（インデックスが無い間は全部取りに行く）", async () => {
    const { setJmaTileIndex, request } = await load();
    fetchMock.mockImplementation(async () => new Response(new Uint8Array([1, 2, 3])));
    const abort = new AbortController();
    const { data } = await request(EMPTY_PNG_URL, abort);
    expect(fetchMock).toHaveBeenCalledWith(EMPTY_PNG_URL, { signal: abort.signal });
    expect(new Uint8Array(data as ArrayBuffer)).toEqual(new Uint8Array([1, 2, 3]));

    setJmaTileIndex(INDEX);
    await request(PRESENT_PNG_URL);
    expect(fetchMock).toHaveBeenLastCalledWith(PRESENT_PNG_URL, expect.anything());
  });
});

describe("配信の失敗の記録", () => {
  it("5xxは空タイルで代替し、要素配下のURLを失敗として記録して購読者へ知らせる", async () => {
    const { request, jmaTileFailures, subscribeJmaTileFailures } = await load();
    const listener = vi.fn();
    subscribeJmaTileFailures(listener);
    fetchMock.mockResolvedValue(new Response(null, { status: 503 }));

    const { data } = await request(PRESENT_PNG_URL);
    expect(isFullyTransparentPng(data as Uint8Array)).toBe(true);
    expect(jmaTileFailures()).toEqual(new Map([["inund", PREFIX]]));
    expect(listener).toHaveBeenCalledTimes(1);
    expect(debugLog).toHaveBeenCalledWith("weather", expect.any(String), expect.anything(), "warn");
  });

  it("同じ失敗が続く間は記録の参照を変えず、知らせもしない", async () => {
    const { request, jmaTileFailures, subscribeJmaTileFailures } = await load();
    fetchMock.mockResolvedValue(new Response(null, { status: 500 }));
    await request(PRESENT_PNG_URL);
    const recorded = jmaTileFailures();
    const listener = vi.fn();
    subscribeJmaTileFailures(listener);
    await request(`${PREFIX}5/29/13.png`);
    expect(jmaTileFailures()).toBe(recorded);
    expect(listener).not.toHaveBeenCalled();
  });

  it("配信元が応答すれば（404の空応答も含む）その要素の失敗を消す", async () => {
    const { request, jmaTileFailures } = await load();
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 502 }));
    await request(PRESENT_PNG_URL);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 404 }));
    await request(PRESENT_PNG_URL);
    expect(jmaTileFailures().size).toBe(0);
    expect(debugLog).toHaveBeenCalledTimes(1);

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 502 }));
    await request(PRESENT_PNG_URL);
    fetchMock.mockResolvedValueOnce(new Response(new Uint8Array([1])));
    await request(PRESENT_PNG_URL);
    expect(jmaTileFailures().size).toBe(0);
  });

  it("到達できなければ失敗として記録して例外を返す。取り消し（中断）は失敗に数えない", async () => {
    const { request, jmaTileFailures } = await load();
    fetchMock.mockRejectedValueOnce(new DOMException("aborted", "AbortError"));
    await expect(request(PRESENT_PNG_URL)).rejects.toThrow("aborted");
    expect(jmaTileFailures().size).toBe(0);

    fetchMock.mockRejectedValueOnce(new TypeError("network"));
    await expect(request(PRESENT_PNG_URL)).rejects.toThrow("network");
    expect(jmaTileFailures().get("inund")).toBe(PREFIX);
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

// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { inflateSync } from "node:zlib";

import type { JmaTileIndexResponse } from "@/components/Map/jmaTileIndex";

type ProtocolHandler = (params: { url: string }, abort: AbortController) => Promise<{ data: ArrayBuffer | Uint8Array }>;

const { protocolHandlers } = vi.hoisted(() => ({ protocolHandlers: new Map<string, ProtocolHandler>() }));

vi.mock("maplibre-gl", () => ({
  addProtocol: (scheme: string, handler: ProtocolHandler) => protocolHandlers.set(scheme, handler),
}));

const BT = "20260907025000";
const REAL_URL = `https://example.test/api/jma-tile/bosai/jmatile/data/risk/${BT}/immed0/${BT}/surf/rain_mesh/10/909/403.png`;

const INDEX: JmaTileIndexResponse = {
  available: true,
  coverage: {
    min_longitude: 138.35,
    min_latitude: 34.85,
    max_longitude: 140.95,
    max_latitude: 37.2,
  },
  elements: {
    // (909,403)にだけ中身がある。
    rain_mesh: { basetime: BT, validtime: BT, member: "immed0", zooms: { "10": [[909, 403]] } },
  },
};

/** ハンドラが受け取るのと同じ形のタイルURL。 */
function tileUrl(basetime: string, x: number, y: number): string {
  return `https://example.test/api/jma-tile/bosai/jmatile/data/nowc/${basetime}/immed0/${basetime}/surf/rain_mesh/10/${x}/${y}.png`;
}

/** インデックスに載っていない＝空と分かっているタイル。 */
const EMPTY_TILE = tileUrl(BT, 910, 403);
/** インデックスに載っている＝中身があるタイル。 */
const FILLED_TILE = tileUrl(BT, 909, 403);

// このモジュールはインデックスと失敗の記録をモジュールスコープに持つ（ハンドラはMapLibre
// 内部から都度呼ばれるため）。テストごとに読み込み直して初期状態へ戻す——**本番へ
// 「テストのために戻す」口を置かないため**。
let mod: typeof import("@/components/Map/jmaTileProtocol");
let handler: ProtocolHandler;

beforeEach(async () => {
  vi.resetModules();
  protocolHandlers.clear();
  mod = await import("@/components/Map/jmaTileProtocol");
  mod.registerJmaTileProtocol();
  handler = protocolHandlers.get("jmatile") as ProtocolHandler;
  expect(handler).toBeDefined();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** 配信元の応答を差し替え、呼ばれたかを見られるようにする。 */
function stubFetch(status = 200): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(
    async () => ({ ok: status < 400, status, arrayBuffer: async () => new ArrayBuffer(0) }) as Response,
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** 空と分かっているタイルをハンドラから受け取る。 */
async function emptyTileBytes(url: string): Promise<Uint8Array> {
  mod.setJmaTileIndex(INDEX);
  const { data } = await handler({ url: mod.withJmaTileProtocol(url) }, new AbortController());
  return data as Uint8Array;
}

describe("URLのスキーム", () => {
  it("スキームを剥がした実URLへ取りに行く", async () => {
    const fetchMock = stubFetch();

    await handler({ url: mod.withJmaTileProtocol(REAL_URL) }, new AbortController());

    expect(fetchMock).toHaveBeenCalledWith(REAL_URL, expect.anything());
  });

  it("スキームが付いていないURLはそのまま使う", async () => {
    const fetchMock = stubFetch();

    await handler({ url: REAL_URL }, new AbortController());

    expect(fetchMock).toHaveBeenCalledWith(REAL_URL, expect.anything());
  });
});

// 間引きが効いているかは「ネットワークへ出たか」でしか確かめられない。インデックスを
// 保持しているかだけを見ると、古いものを握り続けても気づけない。
describe("インデックスによる間引き", () => {
  it("インデックスが無い間は間引かない", async () => {
    const fetchMock = stubFetch();

    await handler({ url: mod.withJmaTileProtocol(EMPTY_TILE) }, new AbortController());

    expect(fetchMock).toHaveBeenCalled();
  });

  it("available:false も無効として扱う", async () => {
    mod.setJmaTileIndex({ available: false });
    const fetchMock = stubFetch();

    await handler({ url: mod.withJmaTileProtocol(EMPTY_TILE) }, new AbortController());

    expect(fetchMock).toHaveBeenCalled();
  });

  it("空と分かっているタイルはネットワークへ出さない", async () => {
    mod.setJmaTileIndex(INDEX);
    const fetchMock = stubFetch();

    await handler({ url: mod.withJmaTileProtocol(EMPTY_TILE) }, new AbortController());

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("中身のあるタイルは取りに行く", async () => {
    mod.setJmaTileIndex(INDEX);
    const fetchMock = stubFetch();

    await handler({ url: mod.withJmaTileProtocol(FILLED_TILE) }, new AbortController());

    expect(fetchMock).toHaveBeenCalled();
  });

  it("nullへ戻すと間引きが止まる", async () => {
    mod.setJmaTileIndex(INDEX);
    mod.setJmaTileIndex(null);
    const fetchMock = stubFetch();

    await handler({ url: mod.withJmaTileProtocol(EMPTY_TILE) }, new AbortController());

    expect(fetchMock).toHaveBeenCalled();
  });

  it("差し替えるたびに最新のものが使われる", async () => {
    const NEW_BT = "20260907030000";
    mod.setJmaTileIndex(INDEX);
    // basetimeが進んだ新しいインデックスへ差し替え（新しい版では909,403に中身が無い）。
    mod.setJmaTileIndex({
      ...INDEX,
      elements: {
        rain_mesh: { basetime: NEW_BT, validtime: NEW_BT, member: "immed0", zooms: { "10": [[910, 403]] } },
      },
    });
    const fetchMock = stubFetch();

    // 旧basetimeのURLは判定の対象外へ落ちる（古い版で判定し続けない）。
    await handler({ url: mod.withJmaTileProtocol(tileUrl(BT, 910, 403)) }, new AbortController());
    // 新しい版で中身があるタイルも取りに行く。
    await handler({ url: mod.withJmaTileProtocol(tileUrl(NEW_BT, 910, 403)) }, new AbortController());
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // 新しい版に載っていないタイルだけが空。
    await handler({ url: mod.withJmaTileProtocol(tileUrl(NEW_BT, 909, 403)) }, new AbortController());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("空タイルとして返すもの", () => {
  /** PNGのIHDRとIDATから1画素目のRGBAを取り出す。 */
  function firstPixel(png: Uint8Array): { width: number; height: number; rgba: number[] } {
    const view = new DataView(png.buffer, png.byteOffset, png.byteLength);
    let pos = 8;
    let width = 0;
    let height = 0;
    const idat: Uint8Array[] = [];
    while (pos < png.length) {
      const length = view.getUint32(pos);
      const type = String.fromCharCode(...png.slice(pos + 4, pos + 8));
      const data = png.slice(pos + 8, pos + 8 + length);
      if (type === "IHDR") {
        width = view.getUint32(pos + 8);
        height = view.getUint32(pos + 12);
        // カラータイプ6（RGBA）以外だと下の画素の読み方が変わる。
        expect(data[9]).toBe(6);
      }
      if (type === "IDAT") idat.push(data);
      pos += 12 + length;
    }
    const raw = inflateSync(Buffer.concat(idat.map((d) => Buffer.from(d))));
    // 先頭1バイトは行のフィルタ種別。
    return { width, height, rgba: [...raw.slice(1, 5)] };
  }

  it("ラスタは1画素が完全に透明なPNG", async () => {
    const { width, height, rgba } = firstPixel(await emptyTileBytes(EMPTY_TILE));

    expect([width, height]).toEqual([1, 1]);
    // MapLibreはこの1画素をタイル全面へ引き伸ばす。不透明な画素だと地図全体が塗られる
    // （災害レイヤーが関東全域を緑一色にした実例、docs/records/tasks/T754.md）。
    expect(rgba).toEqual([0, 0, 0, 0]);
  });

  it("ラスタの空タイルは要求のたびに別のバッファ", async () => {
    const first = await emptyTileBytes(EMPTY_TILE);
    const second = await emptyTileBytes(EMPTY_TILE);

    expect(first.buffer).not.toBe(second.buffer);
  });
});

// MapLibreはタイルのデータをWorkerへtransferして渡すため、返したArrayBufferはdetachedに
// なる。空タイルを共有のインスタンスで返していると、2回目以降のpostMessageが
// "An ArrayBuffer is detached and could not be cloned"で失敗し、そのタイルが描画されない。
// 空タイルは404（疎な格子状タイルの正常系）でも返るため、実機では常時起きる。
describe("空タイルのバッファ", () => {
  const PBF_URL = "https://example.test/api/jma-tile/bosai/jmatile/data/risk/flood/10/909/403.pbf";

  it("要求のたびに別のバッファを返す（1つ目をtransferしても2つ目が壊れない）", async () => {
    stubFetch(500);

    const first = (await handler({ url: mod.withJmaTileProtocol(PBF_URL) }, new AbortController())).data as Uint8Array;
    const second = (await handler({ url: mod.withJmaTileProtocol(PBF_URL) }, new AbortController())).data as Uint8Array;

    const firstBuffer = first.buffer as ArrayBuffer;
    const secondBuffer = second.buffer as ArrayBuffer;
    expect(firstBuffer).not.toBe(secondBuffer);
    structuredClone(firstBuffer, { transfer: [firstBuffer] });
    expect(firstBuffer.detached).toBe(true);
    expect(secondBuffer.detached).toBe(false);
  });
});

// 配信の障害は空タイルで代替されるため、MapLibreのソースイベントにも地図の見た目にも
// 現れない。「平常時は透明」が正常系のレイヤーで危険度ゼロと見分けるための記録。
describe("配信障害の記録", () => {
  const ELEMENT_PREFIX = `https://example.test/api/jma-tile/bosai/jmatile/data/risk/${BT}/immed0/${BT}/surf/rain_mesh/`;

  it("5xxはその要素の失敗として残り、購読者へ届く", async () => {
    const notified = vi.fn();
    const unsubscribe = mod.subscribeJmaTileFailures(notified);
    stubFetch(503);

    await handler({ url: mod.withJmaTileProtocol(REAL_URL) }, new AbortController());

    expect(mod.jmaTileFailures().get("rain_mesh")).toBe(ELEMENT_PREFIX);
    expect(notified).toHaveBeenCalled();
    unsubscribe();
  });

  it("取得できるようになれば解除される", async () => {
    stubFetch(503);
    await handler({ url: mod.withJmaTileProtocol(REAL_URL) }, new AbortController());
    expect(mod.jmaTileFailures().size).toBe(1);

    stubFetch(200);
    await handler({ url: mod.withJmaTileProtocol(REAL_URL) }, new AbortController());

    expect(mod.jmaTileFailures().size).toBe(0);
  });

  // 疎な格子状タイルでは404が正常系で、配信元が「空」と答えている＝配信は生きている。
  it("404は失敗として数えず、直前の失敗を解除する", async () => {
    stubFetch(503);
    await handler({ url: mod.withJmaTileProtocol(REAL_URL) }, new AbortController());

    stubFetch(404);
    await handler({ url: mod.withJmaTileProtocol(REAL_URL) }, new AbortController());

    expect(mod.jmaTileFailures().size).toBe(0);
  });

  it("配信元へ到達できない場合も失敗として残す", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    await expect(handler({ url: mod.withJmaTileProtocol(REAL_URL) }, new AbortController())).rejects.toThrow();

    expect(mod.jmaTileFailures().get("rain_mesh")).toBe(ELEMENT_PREFIX);
  });

  it("中断（パン・ズームでの取り消し）は失敗として数えない", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new DOMException("aborted", "AbortError");
      }),
    );

    await expect(handler({ url: mod.withJmaTileProtocol(REAL_URL) }, new AbortController())).rejects.toThrow();

    expect(mod.jmaTileFailures().size).toBe(0);
  });

  it("スナップショットは内容が変わらないかぎり同じ参照を返す", async () => {
    stubFetch(503);
    await handler({ url: mod.withJmaTileProtocol(REAL_URL) }, new AbortController());
    const first = mod.jmaTileFailures();
    await handler({ url: mod.withJmaTileProtocol(REAL_URL) }, new AbortController());

    expect(mod.jmaTileFailures()).toBe(first);
  });
});

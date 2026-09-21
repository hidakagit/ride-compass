// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { inflateSync } from "node:zlib";

import {
  emptyRasterTileBytes,
  hasJmaTileIndex,
  isKnownEmptyTileUrl,
  jmaTileFailures,
  registerJmaTileProtocol,
  resetJmaTileFailures,
  setJmaTileIndex,
  subscribeJmaTileFailures,
  toRealUrl,
  withJmaTileProtocol,
} from "@/components/Map/jmaTileProtocol";
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

afterEach(() => {
  setJmaTileIndex(null);
  resetJmaTileFailures();
  vi.restoreAllMocks();
});

describe("URLのスキーム変換", () => {
  it("付けて剥がすと元に戻る", () => {
    expect(toRealUrl(withJmaTileProtocol(REAL_URL))).toBe(REAL_URL);
  });

  it("スキームが付いていないURLはそのまま", () => {
    expect(toRealUrl(REAL_URL)).toBe(REAL_URL);
  });
});

describe("インデックスの保持", () => {
  it("null を渡すと無効（間引きなし）になる", () => {
    setJmaTileIndex(INDEX);
    expect(hasJmaTileIndex()).toBe(true);

    setJmaTileIndex(null);
    expect(hasJmaTileIndex()).toBe(false);
  });

  it("available:false は無効として扱う", () => {
    setJmaTileIndex({ available: false });
    expect(hasJmaTileIndex()).toBe(false);
  });
});

// ハンドラ本体はmaplibre-glへ登録されるため直接importできない。同じ判定関数
// （isKnownEmptyTile）を通ることは jmaTileIndex.test.ts で検証しているので、ここでは
// 「インデックスの差し替えがハンドラ側へ反映される」ことだけを担保する。
describe("インデックス差し替えの反映", () => {
  const NEW_BT = "20260907030000";
  /** ハンドラが受け取るのと同じ形のタイルURL。 */
  function tileUrl(basetime: string, x: number, y: number): string {
    return `https://example.test/api/jma-tile/bosai/jmatile/data/nowc/${basetime}/immed0/${basetime}/surf/rain_mesh/10/${x}/${y}.png`;
  }

  beforeEach(() => {
    setJmaTileIndex(null);
  });

  it("差し替えるたびに最新のものが使われる", () => {
    setJmaTileIndex(INDEX);
    // 中身のあるタイルは素通しせず取りに行く。載っていないタイルは空と分かっている。
    expect(isKnownEmptyTileUrl(tileUrl(BT, 909, 403))).toBe(false);
    expect(isKnownEmptyTileUrl(tileUrl(BT, 910, 403))).toBe(true);

    // basetimeが進んだ新しいインデックスへ差し替え（新しい版では909,403に中身が無い）。
    setJmaTileIndex({
      ...INDEX,
      elements: {
        rain_mesh: { basetime: NEW_BT, validtime: NEW_BT, member: "immed0", zooms: { "10": [[910, 403]] } },
      },
    });

    // 旧basetimeのURLは判定の対象外へ落ちる（古い版で判定し続けない）。
    expect(isKnownEmptyTileUrl(tileUrl(BT, 910, 403))).toBe(false);
    // 新しい版の中身は素通ししない。載っていないタイルだけが空。
    expect(isKnownEmptyTileUrl(tileUrl(NEW_BT, 910, 403))).toBe(false);
    expect(isKnownEmptyTileUrl(tileUrl(NEW_BT, 909, 403))).toBe(true);
  });
});

describe("空タイルとして返すPNG", () => {
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

  it("1画素が完全に透明である", () => {
    const { width, height, rgba } = firstPixel(emptyRasterTileBytes());

    expect([width, height]).toEqual([1, 1]);
    // MapLibreはこの1画素をタイル全面へ引き伸ばす。不透明な画素だと地図全体が塗られる
    // （災害レイヤーが関東全域を緑一色にした実例、docs/records/tasks/T754.md）。
    expect(rgba).toEqual([0, 0, 0, 0]);
  });
});

// MapLibreはタイルのデータをWorkerへtransferして渡すため、返したArrayBufferはdetachedに
// なる。空タイルを共有のインスタンスで返していると、2回目以降のpostMessageが
// "An ArrayBuffer is detached and could not be cloned"で失敗し、そのタイルが描画されない。
// 空タイルは404（疎な格子状タイルの正常系）でも返るため、実機では常時起きる。
describe("空タイルのバッファ", () => {
  const PBF_URL = "https://example.test/api/jma-tile/bosai/jmatile/data/risk/flood/10/909/403.pbf";

  function handler(): ProtocolHandler {
    registerJmaTileProtocol();
    const found = protocolHandlers.get("jmatile");
    expect(found).toBeDefined();
    return found as ProtocolHandler;
  }

  it("要求のたびに別のバッファを返す（1つ目をtransferしても2つ目が壊れない）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false }) as Response),
    );
    const request = handler();

    const first = (await request({ url: withJmaTileProtocol(PBF_URL) }, new AbortController())).data as Uint8Array;
    const second = (await request({ url: withJmaTileProtocol(PBF_URL) }, new AbortController())).data as Uint8Array;

    const firstBuffer = first.buffer as ArrayBuffer;
    const secondBuffer = second.buffer as ArrayBuffer;
    expect(firstBuffer).not.toBe(secondBuffer);
    structuredClone(firstBuffer, { transfer: [firstBuffer] });
    expect(firstBuffer.detached).toBe(true);
    expect(secondBuffer.detached).toBe(false);

    vi.unstubAllGlobals();
  });

  it("ラスタの空タイルも共有しない", async () => {
    expect(emptyRasterTileBytes().buffer).not.toBe(emptyRasterTileBytes().buffer);
  });
});

// 配信の障害は空タイルで代替されるため、MapLibreのソースイベントにも地図の見た目にも
// 現れない。「平常時は透明」が正常系のレイヤーで危険度ゼロと見分けるための記録。
describe("配信障害の記録", () => {
  const ELEMENT_PREFIX = `https://example.test/api/jma-tile/bosai/jmatile/data/risk/${BT}/immed0/${BT}/surf/rain_mesh/`;

  function handler(): ProtocolHandler {
    registerJmaTileProtocol();
    return protocolHandlers.get("jmatile") as ProtocolHandler;
  }

  function stubStatus(status: number): void {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: status < 400, status, arrayBuffer: async () => new ArrayBuffer(0) }) as Response),
    );
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("5xxはその要素の失敗として残り、購読者へ届く", async () => {
    const notified = vi.fn();
    const unsubscribe = subscribeJmaTileFailures(notified);
    stubStatus(503);

    await handler()({ url: withJmaTileProtocol(REAL_URL) }, new AbortController());

    expect(jmaTileFailures().get("rain_mesh")).toBe(ELEMENT_PREFIX);
    expect(notified).toHaveBeenCalled();
    unsubscribe();
  });

  it("取得できるようになれば解除される", async () => {
    stubStatus(503);
    await handler()({ url: withJmaTileProtocol(REAL_URL) }, new AbortController());
    expect(jmaTileFailures().size).toBe(1);

    stubStatus(200);
    await handler()({ url: withJmaTileProtocol(REAL_URL) }, new AbortController());

    expect(jmaTileFailures().size).toBe(0);
  });

  // 疎な格子状タイルでは404が正常系で、配信元が「空」と答えている＝配信は生きている。
  it("404は失敗として数えず、直前の失敗を解除する", async () => {
    stubStatus(503);
    await handler()({ url: withJmaTileProtocol(REAL_URL) }, new AbortController());

    stubStatus(404);
    await handler()({ url: withJmaTileProtocol(REAL_URL) }, new AbortController());

    expect(jmaTileFailures().size).toBe(0);
  });

  it("配信元へ到達できない場合も失敗として残す", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    await expect(handler()({ url: withJmaTileProtocol(REAL_URL) }, new AbortController())).rejects.toThrow();

    expect(jmaTileFailures().get("rain_mesh")).toBe(ELEMENT_PREFIX);
  });

  it("中断（パン・ズームでの取り消し）は失敗として数えない", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new DOMException("aborted", "AbortError");
      }),
    );

    await expect(handler()({ url: withJmaTileProtocol(REAL_URL) }, new AbortController())).rejects.toThrow();

    expect(jmaTileFailures().size).toBe(0);
  });

  it("スナップショットは内容が変わらないかぎり同じ参照を返す", async () => {
    stubStatus(503);
    await handler()({ url: withJmaTileProtocol(REAL_URL) }, new AbortController());
    const first = jmaTileFailures();
    await handler()({ url: withJmaTileProtocol(REAL_URL) }, new AbortController());

    expect(jmaTileFailures()).toBe(first);
  });
});

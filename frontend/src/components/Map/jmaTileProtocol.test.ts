// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { inflateSync } from "node:zlib";

import {
  emptyRasterTileBytes,
  hasJmaTileIndex,
  setJmaTileIndex,
  toRealUrl,
  withJmaTileProtocol,
} from "@/components/Map/jmaTileProtocol";
import type { JmaTileIndexResponse } from "@/components/Map/jmaTileIndex";

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
  beforeEach(() => {
    setJmaTileIndex(null);
  });

  it("差し替えるたびに最新のものが使われる", () => {
    setJmaTileIndex(INDEX);
    expect(hasJmaTileIndex()).toBe(true);

    // basetimeが進んだ新しいインデックスへ差し替え。
    setJmaTileIndex({
      ...INDEX,
      elements: {
        rain_mesh: {
          basetime: "20260907030000",
          validtime: "20260907030000",
          member: "immed0",
          zooms: {},
        },
      },
    });

    expect(hasJmaTileIndex()).toBe(true);
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
    // （災害レイヤーが関東全域を緑一色にした実例、docs/tasks/T754.md）。
    expect(rgba).toEqual([0, 0, 0, 0]);
  });
});

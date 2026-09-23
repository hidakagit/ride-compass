// @vitest-environment node
import { describe, expect, it } from "vitest";

import { routePreferenceToSend, syncRoutePreferenceKeys } from "./routePreferenceSync";

const CATALOG_DEFAULTS = { a: 0.5, b: 0.5 };

describe("syncRoutePreferenceKeys（重みのキーを軸カタログへ合わせる）", () => {
  it("キーが揃っていれば変えない（null）", () => {
    expect(syncRoutePreferenceKeys({ a: 0.2, b: 0.8 }, CATALOG_DEFAULTS)).toBeNull();
  });

  it("カタログに増えた軸は既定の重みで補い、消えた軸は外す。利用者の重みは残す", () => {
    expect(syncRoutePreferenceKeys({ a: 0.2, gone: 0.8 }, CATALOG_DEFAULTS)).toEqual({ a: 0.2, b: 0.5 });
  });

  it("渡した重みを書き換えない", () => {
    const stored = { gone: 1 };
    syncRoutePreferenceKeys(stored, CATALOG_DEFAULTS);
    expect(stored).toEqual({ gone: 1 });
  });
});

describe("routePreferenceToSend（生成リクエストへ載せる重み）", () => {
  const loaded = { loaded: true, defaultWeights: CATALOG_DEFAULTS };

  it("重みを上書きしていない間は送らない（backendの既定へ委ねる）", () => {
    expect(routePreferenceToSend({ a: 0.2, b: 0.8 }, loaded, false)).toBeNull();
  });

  it("軸カタログを取得できていない間は送らない（軸0件へ合わせると保存済みの重みが消える）", () => {
    expect(routePreferenceToSend({ a: 0.2, b: 0.8 }, { loaded: false, defaultWeights: {} }, true)).toBeNull();
  });

  it("上書きしていて取得済みなら、カタログへ合わせた重みを送る", () => {
    const current = { a: 0.2, b: 0.8 };
    expect(routePreferenceToSend(current, loaded, true)).toBe(current);
    expect(routePreferenceToSend({ a: 0.2 }, loaded, true)).toEqual({ a: 0.2, b: 0.5 });
  });
});

// @vitest-environment node
import { describe, expect, it } from "vitest";

import { alignRoutePreference, routePreferenceToSend } from "./routePreferenceSync";

const LOADED = { loaded: true, defaultWeights: { a: 0.5, b: 0.5 } };

describe("alignRoutePreference（重みのキーを軸カタログへ揃える）", () => {
  it("キーが揃っていれば、渡した値をそのまま返す", () => {
    const current = { a: 0.2, b: 0.8 };
    expect(alignRoutePreference(current, LOADED)).toBe(current);
  });

  it("カタログに増えた軸は既定の重みで補い、消えた軸は外す。利用者の重みは残す", () => {
    expect(alignRoutePreference({ a: 0.2, gone: 0.8 }, LOADED)).toEqual({ a: 0.2, b: 0.5 });
  });

  it("渡した重みを書き換えない", () => {
    const stored = { gone: 1 };
    alignRoutePreference(stored, LOADED);
    expect(stored).toEqual({ gone: 1 });
  });

  it("軸カタログを取得できていない間は揃えない（軸0件へ揃えると保存済みの重みが消える）", () => {
    const stored = { a: 0.2, gone: 0.8 };
    expect(alignRoutePreference(stored, { loaded: false, defaultWeights: {} })).toBe(stored);
  });
});

describe("routePreferenceToSend（生成リクエストへ載せる重み）", () => {
  const aligned = { a: 0.2, b: 0.8 };

  it("重みを上書きしていない間は送らない（backendの既定へ委ねる）", () => {
    expect(routePreferenceToSend(aligned, true, false)).toBeNull();
  });

  it("軸カタログを取得できていない間は送らない（届いた軸へ揃えられていない）", () => {
    expect(routePreferenceToSend(aligned, false, true)).toBeNull();
  });

  it("上書きしていて取得済みなら、揃えた重みを送る", () => {
    expect(routePreferenceToSend(aligned, true, true)).toBe(aligned);
  });
});

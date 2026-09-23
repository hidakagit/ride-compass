// @vitest-environment node
import { describe, expect, it } from "vitest";
import { routePreferenceToSend, syncRoutePreferenceKeys } from "./routePreferenceSync";

describe("syncRoutePreferenceKeys", () => {
  it("カタログから消えた軸（unpublish後）のキーを削除する", () => {
    const result = syncRoutePreferenceKeys(
      { gradient: 0.5, surface_q: 0.3, night: 0.2 },
      { gradient: 0.1, surface_q: 0.1 },
    );
    expect(result).toEqual({ gradient: 0.5, surface_q: 0.3 });
  });

  it("カタログに新しく現れた軸の既定重みを補う", () => {
    const result = syncRoutePreferenceKeys({ gradient: 0.5 }, { gradient: 0.1, surface_q: 0.1 });
    expect(result).toEqual({ gradient: 0.5, surface_q: 0.1 });
  });

  it("キー集合が既に一致している場合はnullを返す", () => {
    const result = syncRoutePreferenceKeys({ gradient: 0.5, surface_q: 0.3 }, { gradient: 0.1, surface_q: 0.1 });
    expect(result).toBeNull();
  });
});

describe("routePreferenceToSend（生成リクエストへ載せる重み）", () => {
  const catalog = { loaded: true, defaultWeights: { gradient: 0.1, surface_q: 0.1 } };

  it("重みを上書きしていない間は送らず、backendの既定へ委ねる", () => {
    expect(routePreferenceToSend({ gradient: 0.5 }, catalog, false)).toBeNull();
  });

  it("軸カタログを取得できていない間は送らない", () => {
    expect(routePreferenceToSend({ gradient: 0.5 }, { loaded: false, defaultWeights: {} }, true)).toBeNull();
  });

  it("上書き中で軸カタログがあれば、キーをカタログへ揃えて送る", () => {
    expect(routePreferenceToSend({ gradient: 0.5, night: 0.2 }, catalog, true)).toEqual({
      gradient: 0.5,
      surface_q: 0.1,
    });
  });
});

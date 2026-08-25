// @vitest-environment node
import { describe, expect, it } from "vitest";
import { syncRoutePreferenceKeys } from "./routePreferenceSync";

describe("syncRoutePreferenceKeys", () => {
  it("カタログから消えた軸（unpublish後）のキーを削除する", () => {
    const result = syncRoutePreferenceKeys(
      { gradient: 0.5, surface_q: 0.3, night: 0.2 },
      { gradient: 0.1, surface_q: 0.1 }
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

// `useMapView.ts`——地図の見え方の状態（保存と復元）と、そこから地図・操作部品へ渡す値。
//
// ここで見ないもの:
// - 状態から値を導く規則そのもの → `lens.test.ts`・`overlayChips.test.ts`・`legendFilters.test.ts`
// - 気象レイヤーの取得 → `useDynamicWeatherLayers.test.ts`
// - 専用配信の値の取得 → `useDedicatedWayValues.test.ts`
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildDefaultLayerVisibility, type MapLayerId } from "@/components/Map/mapLayers";
import { EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";

import { catalogOf, dedicatedEntry, rampEntry } from "./__fixtures__/catalog";
import { useMapView } from "./useMapView";

type MapViewInputs = Parameters<typeof useMapView>[0];

// 軸カタログと気象レイヤーは外部へ取りに行くため、取りに行かない代役へ差し替える（ネットワーク境界）。
const SOURCES = vi.hoisted(() => ({ catalog: undefined as unknown as AxisCatalog }));
vi.mock("@/hooks/useAxisCatalog", () => ({ useAxisCatalog: () => SOURCES.catalog }));
vi.mock("@/hooks/useDynamicWeatherLayers", () => ({
  useDynamicWeatherLayers: () => ({ dynamicWeather: {}, dynamicWeatherDataStatus: {} }),
}));

const CATALOG = catalogOf([rampEntry("r", [1]), dedicatedEntry("d", [0])]);
const AT = new Date("2026-09-01T00:00:00Z");

function inputs(hasDetail = false): MapViewInputs {
  return {
    hasSelectedRoute: hasDetail,
    hasDetail,
    ride: { bearingDeg: 0, at: AT, speedKmh: 20 },
    now: AT,
    usedWeights: null,
  };
}

describe("useMapView", () => {
  beforeEach(() => {
    window.localStorage.clear();
    SOURCES.catalog = CATALOG;
  });
  afterEach(() => window.localStorage.clear());

  it("軸を指す保存済みのレンズは、軸カタログが届いてから復元して、その軸で全道路を塗る", () => {
    window.localStorage.setItem("ridecompass:route-style-mode", "d");
    SOURCES.catalog = EMPTY_CATALOG;
    const { result, rerender } = renderHook(() => useMapView(inputs()));
    expect(result.current.lens).toBe("difficulty");

    SOURCES.catalog = CATALOG;
    rerender();
    expect(result.current.look.lens).toBe("d");
    expect(result.current.look.paintedAxisId).toBe("d");
  });

  it("レンズを変えると保存し、ルート確定後に周囲を塗らない設定なら全道路の塗りだけを外す", () => {
    const { result, rerender } = renderHook((props: MapViewInputs) => useMapView(props), {
      initialProps: inputs(),
    });
    act(() => result.current.lensControl.onLensChange("r"));
    expect(window.localStorage.getItem("ridecompass:route-style-mode")).toBe("r");
    expect(result.current.look.paintedAxisId).toBe("r");

    act(() => result.current.lensControl.onKeepAfterRouteChange(false));
    rerender(inputs(true));
    expect(result.current.look.paintedAxisId).toBeNull();
    expect(result.current.look.lens).toBe("r");
  });

  it("レンズを選ぶと、ルートのレイヤーがOFFならONにする", () => {
    const { result } = renderHook(() => useMapView(inputs()));
    act(() => result.current.bulk.hideAllLayers());
    expect(result.current.look.layerVisibility.route).toBe(false);
    act(() => result.current.lensControl.onLensChange("r"));
    expect(result.current.look.layerVisibility.route).toBe(true);
  });

  it("保存したレイヤーのON/OFFを復元し、地図とチップの両方へ同じ値を渡す", () => {
    const defaults = buildDefaultLayerVisibility();
    const [someId] = Object.keys(defaults) as MapLayerId[];
    window.localStorage.setItem("ridecompass:layer-visibility", JSON.stringify({ [someId]: !defaults[someId] }));
    const { result } = renderHook(() => useMapView(inputs()));
    expect(result.current.look.layerVisibility[someId]).toBe(!defaults[someId]);
    expect(result.current.overlayControls.layers.find((chip) => chip.id === someId)?.on).toBe(!defaults[someId]);
  });

  it("レンズの凡例で隠した段は、操作部品には即座に、地図には遅れて届き、まとめて戻せる", () => {
    vi.useFakeTimers();
    try {
      window.localStorage.setItem("ridecompass:route-style-mode", "d");
      const { result } = renderHook(() => useMapView(inputs()));
      act(() => result.current.lensControl.onToggleLegendKey("step-0"));
      expect(result.current.lensControl.hiddenLegendKeys).toEqual(["step-0"]);
      expect(result.current.look.hiddenLegendKeys).toEqual({});
      expect(result.current.bulk.anyLegendHidden).toBe(true);

      act(() => vi.advanceTimersByTime(400));
      expect(result.current.look.hiddenLegendKeys).toEqual({ d: ["step-0"] });

      act(() => result.current.bulk.showAllLegendRows());
      expect(result.current.bulk.anyLegendHidden).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});

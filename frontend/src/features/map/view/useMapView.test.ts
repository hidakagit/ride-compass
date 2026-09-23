// `useMapView.ts`——地図の見え方の状態（保存と復元）と、そこから地図・操作部品へ渡す値。
//
// ここで見ないもの:
// - 状態から値を導く規則そのもの → `lens.test.ts`・`overlayChips.test.ts`・`legendFilters.test.ts`
// - 気象レイヤーの取得・出発時刻の追従 → `useDynamicWeatherLayers.test.ts`
// - 専用配信の値の取得 → `useDedicatedWayValues.test.ts`
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildDefaultLayerVisibility, type MapLayerId } from "@/components/Map/mapLayers";
import { EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";

import { catalogOf, dedicatedEntry, rampEntry } from "./__fixtures__/catalog";
import { useMapView, type MapViewInputs } from "./useMapView";

// 気象レイヤーは外部へ取りに行くため、取りに行かない代役へ差し替える（ネットワーク境界）。
const WEATHER = vi.hoisted(() => ({
  dynamicWeather: {},
  dynamicWeatherDataStatus: {},
  setDynamicLayerTargetTime: () => {},
  handleDynamicLayerNow: () => {},
  departureTimePinned: false,
  dynamicLayerTargetTime: new Date("2026-09-01T00:00:00Z"),
}));
vi.mock("@/hooks/useDynamicWeatherLayers", () => ({ useDynamicWeatherLayers: () => WEATHER }));

const CATALOG = catalogOf([rampEntry("r", [1]), dedicatedEntry("d", [0])]);
const NO_WEIGHTS = {};
const NO_COLORS = {};
const RIDE = { travelBearingDeg: 0, assumedSpeedKmh: 20 };

function inputs(catalog: AxisCatalog, hasDetail = false): MapViewInputs {
  return {
    catalog,
    route: { hasRoutes: hasDetail, hasDetail },
    ride: RIDE,
    axisWeights: NO_WEIGHTS,
    axisColors: NO_COLORS,
  };
}

describe("useMapView", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it("軸を指す保存済みのレンズは、軸カタログが届いてから復元して地図を塗り分ける", () => {
    window.localStorage.setItem("ridecompass:route-style-mode", "d");
    const { result, rerender } = renderHook((props: MapViewInputs) => useMapView(props), {
      initialProps: inputs(EMPTY_CATALOG),
    });
    expect(result.current.lens).toBe("difficulty");

    rerender(inputs(CATALOG));
    expect(result.current.lens).toBe("d");
    expect(result.current.look.routeStyleModeId).toBe("d");
    expect(result.current.look.dedicatedWayValueVisibility).toEqual({ dAxis: true });
    expect(result.current.look.axisVisibility).toEqual({ "axis:r": false });
  });

  it("レンズを変えると保存し、ルート確定後に周囲を塗らない設定なら全道路の塗りだけを外す", () => {
    const { result, rerender } = renderHook((props: MapViewInputs) => useMapView(props), {
      initialProps: inputs(CATALOG),
    });
    act(() => result.current.controls.lens.onLensChange("r"));
    expect(window.localStorage.getItem("ridecompass:route-style-mode")).toBe("r");
    expect(result.current.look.axisVisibility).toEqual({ "axis:r": true });

    act(() => result.current.controls.lens.onKeepAfterRouteChange(false));
    rerender(inputs(CATALOG, true));
    expect(result.current.look.axisVisibility).toEqual({ "axis:r": false });
    expect(result.current.look.routeStyleModeId).toBe("r");
  });

  it("保存したレイヤーのON/OFFを復元し、地図とチップの両方へ同じ値を渡す", () => {
    const defaults = buildDefaultLayerVisibility();
    const [someId] = Object.keys(defaults) as MapLayerId[];
    window.localStorage.setItem("ridecompass:layer-visibility", JSON.stringify({ [someId]: !defaults[someId] }));
    const { result } = renderHook(() => useMapView(inputs(CATALOG)));
    expect(result.current.look.staticLayerVisibility[someId]).toBe(!defaults[someId]);
    expect(result.current.controls.overlay.layers.find((chip) => chip.id === someId)?.on).toBe(!defaults[someId]);
    expect(result.current.controls.reset.layersChanged).toBe(true);
  });

  it("レンズの凡例で隠した段は、全道路の塗りとルート線の両方で隠れる", () => {
    window.localStorage.setItem("ridecompass:route-style-mode", "d");
    const { result } = renderHook(() => useMapView(inputs(CATALOG)));
    act(() => result.current.controls.lens.onToggleLegendKey("step-0"));
    expect(result.current.controls.lens.hiddenLegendKeys).toEqual(["step-0"]);
    expect(result.current.look.dedicatedWayValueHiddenBands.get("d")).toEqual(["step-0"]);
    expect(result.current.look.hiddenRouteLegendKeys).toEqual(["step-0"]);
    expect(result.current.controls.reset.legendFiltered).toBe(true);

    act(() => result.current.controls.reset.clearLegendFilters());
    expect(result.current.look.hiddenRouteLegendKeys).toEqual([]);
  });
});

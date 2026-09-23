import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AxisCatalog } from "@/lib/axisCatalog";

const mocks = vi.hoisted(() => ({
  catalog: { current: undefined as unknown as AxisCatalog },
  tileVersionsReady: { current: true },
  useDynamicWeatherLayers: vi.fn(),
  useDedicatedWayValues: vi.fn(),
}));
vi.mock("@/hooks/useAxisCatalog", () => ({ useAxisCatalog: () => mocks.catalog.current }));
vi.mock("@/features/map/useTileVersionsReady", () => ({ useTileVersionsReady: () => mocks.tileVersionsReady.current }));
vi.mock("@/features/map/useDynamicWeatherLayers", () => ({ useDynamicWeatherLayers: mocks.useDynamicWeatherLayers }));
vi.mock("@/features/map/useDedicatedWayValues", () => ({ useDedicatedWayValues: mocks.useDedicatedWayValues }));
// 凡例の絞り込みを地図へ反映するまでの間引きはuseDebouncedValueの持ち物。
vi.mock("@/hooks/useDebouncedValue", () => ({ useDebouncedValue: <T>(value: T) => value }));

import {
  buildDefaultLayerVisibility,
  TILE_VERSIONS_MISSING_NOTICE,
  TILE_ZOOM_TOO_WIDE_NOTICE,
} from "@/features/map/layers/mapLayers";
import { DISASTER_LAYER_ID } from "@/features/map/scene/legends";
import { LENS_DIFFICULTY_ID } from "@/lib/mapDisplay/routeStyleModes";

import { catalogOf, dedicatedEntry, rampEntry } from "./__fixtures__/catalog";
import { useMapView } from "./useMapView";

const CATALOG: AxisCatalog = {
  ...catalogOf([rampEntry("ramp", [10]), dedicatedEntry("dedicated", [1])]),
  loaded: true,
  failed: false,
};
const RIDE = { bearingDeg: 90, at: new Date("2026-09-24T00:00:00Z"), speedKmh: 20 };
const EMPTY_WEATHER = { dynamicWeather: {}, dynamicWeatherDataStatus: {} };

type Inputs = Parameters<typeof useMapView>[0];
const INPUTS: Inputs = { hasSelectedRoute: false, hasDetail: false, ride: RIDE, now: RIDE.at, usedWeights: null };

function render(inputs: Partial<Inputs> = {}) {
  return renderHook((props: Inputs) => useMapView(props), { initialProps: { ...INPUTS, ...inputs } });
}
const chip = (state: ReturnType<typeof useMapView>, id: string) =>
  state.overlayControls.layers.find((entry) => entry.id === id)!;
const fetchedAxisIds = () =>
  (mocks.useDedicatedWayValues.mock.lastCall?.[0] ?? []).map((axis: { axisId: string }) => axis.axisId);

beforeEach(() => {
  localStorage.clear();
  mocks.catalog.current = CATALOG;
  mocks.tileVersionsReady.current = true;
  mocks.useDynamicWeatherLayers.mockReset().mockReturnValue(EMPTY_WEATHER);
  mocks.useDedicatedWayValues.mockReset().mockReturnValue(new Map());
});

describe("レイヤーの表示", () => {
  it("チップで切り替えた表示は、地図・チップの両方に映り、次に開いたときも残る", () => {
    const { result, unmount } = render();
    act(() => result.current.overlayControls.onToggle("surface", true));
    expect(result.current.look.layerVisibility.surface).toBe(true);
    expect(chip(result.current, "surface").on).toBe(true);
    unmount();

    expect(render().result.current.look.layerVisibility.surface).toBe(true);
  });

  it("まとめて消すと全レイヤーがOFFになる", () => {
    const { result } = render();
    expect(result.current.bulk.anyLayerOn).toBe(true);
    act(() => result.current.bulk.hideAllLayers());
    expect(Object.values(result.current.look.layerVisibility).every((on) => on === false)).toBe(true);
    expect(result.current.bulk.anyLayerOn).toBe(false);
  });
});

describe("レンズ", () => {
  it("既定は総合難易度。選ぶとルートのレイヤーがOFFでもONにし、次に開いたときも残る", () => {
    const { result, unmount } = render();
    expect(result.current.lens).toBe(LENS_DIFFICULTY_ID);
    act(() => result.current.overlayControls.onToggle("route", false));
    act(() => result.current.lensControl.onLensChange("ramp"));
    expect(result.current.lens).toBe("ramp");
    expect(result.current.look.layerVisibility.route).toBe(true);
    unmount();
    expect(render().result.current.lens).toBe("ramp");
  });

  it("保存したレンズの軸は、カタログが届いてから読み直す（届く前は読めずに既定）", () => {
    localStorage.setItem("ridecompass:route-style-mode", "ramp");
    mocks.catalog.current = { ...catalogOf([]), loaded: false, failed: false };
    const { result, rerender } = render();
    expect(result.current.lens).toBe(LENS_DIFFICULTY_ID);
    mocks.catalog.current = CATALOG;
    rerender(INPUTS);
    expect(result.current.lens).toBe("ramp");
  });

  it("専用配信軸の値は、その軸で全道路を塗っている間だけ取る（ルート確定後は塗り続ける設定の間だけ）", () => {
    const { result, rerender } = render();
    act(() => result.current.lensControl.onLensChange("dedicated"));
    expect(fetchedAxisIds()).toEqual(["dedicated"]);
    expect(mocks.useDedicatedWayValues.mock.lastCall?.slice(2)).toEqual([RIDE.bearingDeg, RIDE.at, RIDE.speedKmh]);

    act(() => result.current.lensControl.onKeepAfterRouteChange(false));
    rerender({ ...INPUTS, hasSelectedRoute: true, hasDetail: true });
    expect(fetchedAxisIds()).toEqual([]);
    expect(result.current.look.paintedAxisId).toBeNull();

    act(() => result.current.lensControl.onLensChange("ramp"));
    rerender({ ...INPUTS, hasDetail: false });
    expect(fetchedAxisIds()).toEqual([]);
  });

  it("塗っている専用配信軸の取得状態をレンズへ出す", () => {
    mocks.useDedicatedWayValues.mockReturnValue(
      new Map([["dedicated", { values: new Map(), loading: false, error: true, hasFetched: true }]]),
    );
    const { result } = render();
    expect(result.current.lensControl.dataStatus).toBeUndefined();
    act(() => result.current.lensControl.onLensChange("dedicated"));
    expect(result.current.lensControl.dataStatus).toBe("error");
  });

  it("選択肢は公開軸で、全道路を塗れない軸にはルートだけの印が付き、生成に使わなかった軸は未使用", () => {
    const { result } = render({ usedWeights: { ramp: 1 } });
    const options = result.current.lensControl.axisOptions;
    expect(options.map((option) => option.id)).toEqual(CATALOG.axes.map((axis) => axis.axisId));
    expect(options.find((option) => option.id === "ramp")).toMatchObject({ routeOnly: false, unused: false });
    expect(options.find((option) => option.id === "dedicated")).toMatchObject({ routeOnly: false, unused: true });
  });
});

describe("凡例で隠した行", () => {
  it("レンズの凡例で隠した行は、地図・ルートのチップにも同じ保存先で効き、まとめて戻せる", () => {
    const { result, rerender } = render();
    act(() => result.current.lensControl.onLensChange("ramp"));
    const [firstBand] = result.current.lensControl.legend;
    act(() => result.current.lensControl.onToggleLegendKey(firstBand.key));
    expect(result.current.lensControl.hiddenLegendKeys).toEqual([firstBand.key]);
    expect(result.current.look.hiddenLegendKeys).toEqual({ ramp: [firstBand.key] });
    expect(result.current.bulk.anyLegendHidden).toBe(true);

    rerender({ ...INPUTS, hasSelectedRoute: true, hasDetail: true });
    const routeLegend = chip(result.current, "route").legendDetails;
    expect(routeLegend?.[0]).toMatchObject({ axisId: "ramp" });

    act(() => result.current.bulk.showAllLegendRows());
    expect(result.current.look.hiddenLegendKeys).toEqual({});
    expect(result.current.bulk.anyLegendHidden).toBe(false);
  });

  it("災害の▶パネルで隠した要素を、気象レイヤーの取得へ渡す", () => {
    const { result } = render();
    act(() => result.current.overlayControls.onLegendEntryToggle(DISASTER_LAYER_ID, "thunder"));
    expect(mocks.useDynamicWeatherLayers.mock.lastCall?.[0]).toMatchObject({ hiddenDisasterSources: ["thunder"] });
    act(() => result.current.overlayControls.onLegendAxisSetHidden(DISASTER_LAYER_ID, []));
    expect(mocks.useDynamicWeatherLayers.mock.lastCall?.[0]).toMatchObject({ hiddenDisasterSources: [] });
  });
});

describe("チップの案内", () => {
  it("地図の表示範囲が届くと、そのズームで出ないレイヤーに案内を出す", () => {
    const { result } = render();
    expect(chip(result.current, "highway").notice).toBeNull();
    act(() => result.current.look.onViewportChange({ west: 139, south: 35, east: 140, north: 36, zoom: 3 }));
    expect(chip(result.current, "highway").notice).toBe(TILE_ZOOM_TOO_WIDE_NOTICE);
  });

  it("カタログを取り終えてもタイル世代が無ければ、世代が要るレイヤーに出せない理由を出す", () => {
    mocks.tileVersionsReady.current = false;
    const { result } = render();
    expect(chip(result.current, "highway")).toMatchObject({
      notice: TILE_VERSIONS_MISSING_NOTICE,
      dataStatus: "error",
    });
    expect(chip(result.current, "elevation").notice).toBeNull();
  });

  it("地図が報告した取得状態と、気象レイヤーの取得状態を合わせて出す", () => {
    mocks.useDynamicWeatherLayers.mockReturnValue({
      dynamicWeather: {},
      dynamicWeatherDataStatus: { disaster: "loading" },
    });
    const { result } = render();
    act(() => result.current.look.onLayerDataStatusChange({ surface: "empty" }));
    expect(chip(result.current, "surface").dataStatus).toBe("empty");
    expect(chip(result.current, "disaster").dataStatus).toBe("loading");
  });
});

describe("地図へ渡す値", () => {
  it("中身が変わらない間は同じ参照を渡し（地図が組み直さない）、描き直しを頼むと変える", () => {
    const { result, rerender } = render();
    const before = result.current.look;
    rerender({ ...INPUTS });
    expect(result.current.look).toBe(before);
    act(() => result.current.bulk.redraw());
    expect(result.current.look).not.toBe(before);
    expect(result.current.look.refreshToken).toBe(before.refreshToken + 1);
  });

  it("既定の表示状態は、保存値が無ければレイヤー一覧の既定値", () => {
    expect(render().result.current.look.layerVisibility).toEqual(buildDefaultLayerVisibility());
  });
});

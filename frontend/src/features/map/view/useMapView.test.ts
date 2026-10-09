/**
 * 地図の見え方のフックが、レンズ・レイヤーの表示・凡例で隠した行の状態を持ち、そこから地図への値と操作部品への値を
 * 導くことを見る（docs/modules/frontend/map-axis-coloring.md・static-map-layers.md）。軸カタログ・専用配信の値・気象の
 * 配信元への要求は網の層で応え、取得のフックも間引きも本物を通す。
 *
 * ここで見ないもの: レンズから導く凡例・選択肢・条件の文の中身（`lens.test.ts`）、チップの組み立て（`overlayChips.test.ts`）、
 * 隠した行の保存先の読み書き（`legendFilters.test.ts`）、気象の描画内容と取得状態（`useDynamicWeatherLayers.test.ts`）。
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TILE_VERSIONS_MISSING_NOTICE, TILE_ZOOM_TOO_WIDE_NOTICE } from "@/features/map/layers/mapLayers";
import { ROAD_OTHER_KEY } from "@/features/map/scene/groups/roadLines";
import { LEGEND_NO_DATA_KEY } from "@/lib/mapDisplay/mapColorLegend";
import { onBackend, onSameOrigin } from "@/testing/backendServer";
import { catalogEntry, catalogResponse, dedicatedEntry, rampEntry } from "@/testing/catalogAxes";
import type { AxisCatalogEntry } from "@/types/route";

import { useMapView } from "./useMapView";

const NOW = new Date("2026-10-07T03:00:00Z");
const TILE_VERSIONS = { accident: "a1", poi: "p1", road_surface: "r1" };
const RAMP = rampEntry("axis_ramp", [10, 20]);
const DEDICATED = dedicatedEntry("axis_wind", [10, 20], { dynamic_way_value_conditions: ["bearing_deg"] });
const OTHER_DEDICATED = dedicatedEntry("axis_other", [10, 20]);
/** 道路タイルのズームの、狭い表示範囲（覆うタイルが少ない）。 */
const VIEWPORT = { west: 139.7, south: 35.68, east: 139.701, north: 35.681, zoom: 14 };

type Inputs = Parameters<typeof useMapView>[0];

/** 軸カタログに`catalog`で応え、既定で表示する災害のチップが読む配信元の時刻一覧には空で応える。 */
function serve(catalog: Response | readonly AxisCatalogEntry[] = [RAMP]) {
  onBackend("GET", "/api/axis-catalog", () =>
    catalog instanceof Response ? catalog : Response.json(catalogResponse(catalog, { tile_versions: TILE_VERSIONS })),
  );
  onSameOrigin("GET", "/api/jma-tile/*", () => Response.json([]));
}

function render(inputs: Partial<Inputs> = {}) {
  return renderHook((props: Partial<Inputs>) =>
    useMapView({
      hasSelectedRoute: false,
      hasDetail: false,
      ride: { bearingDeg: 90, at: NOW, speedKmh: 20 },
      now: NOW,
      departureLabel: "12:00",
      routeWeights: {},
      ...inputs,
      ...props,
    }),
  );
}

const chip = (result: { current: ReturnType<typeof useMapView> }, id: string) =>
  result.current.overlayControls.layers.find((layer) => layer.id === id);

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("useMapView", () => {
  it.each([
    { name: "軸カタログにあれば、届いてから戻す", entries: [RAMP], lens: "axis_ramp" },
    { name: "軸カタログに無ければ、総合難易度のまま", entries: [], lens: "difficulty" },
  ])("保存したレンズは、$name", async ({ entries, lens }) => {
    window.localStorage.setItem("ridecompass:route-style-mode", "axis_ramp");
    serve(entries);

    const { result } = render();

    expect(result.current.lensControl.lens).toBe("difficulty");
    await waitFor(() => expect(chip(result, "surface")?.dataStatus).not.toBe("loading"));
    expect(result.current.lensControl.lens).toBe(lens);
    expect(result.current.look.lens).toBe(lens);
  });

  it("レンズを選ぶとルートのレイヤーを表示し、ルートの確定後に周りを塗らない設定なら全道路を塗らない", () => {
    serve();
    const { result, rerender } = render();
    act(() => result.current.lensControl.onRouteShownChange(false));

    act(() => result.current.lensControl.onLensChange("axis_ramp"));

    expect(result.current.look).toMatchObject({ lens: "axis_ramp", paintedAxisId: "axis_ramp" });
    expect(result.current.look.layerVisibility.route).toBe(true);
    rerender({ hasDetail: true });
    act(() => result.current.lensControl.onKeepAfterRouteChange(false));
    expect(result.current.look.paintedAxisId).toBeNull();
  });

  it("レンズの選択肢は公開軸から作り、塗れない軸と生成に使った重みが0の軸を分ける", async () => {
    serve([RAMP, catalogEntry({ axis_id: "axis_plain" })]);

    const { result } = render({ routeWeights: { axis_ramp: 0.5 } });

    await waitFor(() => expect(result.current.lensControl.axisOptions).toHaveLength(2));
    expect(result.current.lensControl.axisOptions).toMatchObject([
      { id: "axis_ramp", unused: false, routeOnly: false },
      { id: "axis_plain", unused: true, routeOnly: true },
    ]);
  });

  it.each([
    { name: "取れなければ失敗", reply: () => new HttpResponse(null, { status: 500 }), status: "error" },
    { name: "値が無ければ空", reply: () => Response.json({}), status: "empty" },
    { name: "値があれば何も言わない", reply: () => Response.json({ way_1: 12 }), status: undefined },
  ])(
    "塗っている専用配信の軸だけ表示範囲の値を取り、走る条件と取得の状態（$name）をレンズに出す",
    async ({ reply, status }) => {
      serve([DEDICATED, OTHER_DEDICATED]);
      onBackend("GET", "/api/region/dynamic-way-values/axis_wind/:z/:x/:y", reply);
      const { result } = render();
      await waitFor(() => expect(result.current.lensControl.axisOptions).toHaveLength(2));

      act(() => result.current.lensControl.onLensChange("axis_wind"));
      act(() => result.current.look.onViewportChange(VIEWPORT));

      expect(result.current.lensControl.conditions).toBe("東へ走る");
      // 表示範囲は間引いてから取るので、その軸の結果が出て取り終えるまで待つ。
      await waitFor(() => expect(result.current.look.dedicatedWayValues.get("axis_wind")?.loading).toBe(false), {
        timeout: 3000,
      });
      expect(result.current.lensControl.dataStatus).toBe(status);
    },
  );

  it("レンズの凡例で隠した行は、凡例へはすぐ、地図へは間引きの待ちのあとに出て（全段をまとめても隠せる）、すべて解除すると戻る", async () => {
    serve();
    const { result } = render();
    await waitFor(() => expect(result.current.lensControl.axisOptions).toHaveLength(1));
    act(() => result.current.lensControl.onLensChange("axis_ramp"));
    const key = result.current.lensControl.legend[0].key;
    vi.useFakeTimers();

    act(() => result.current.lensControl.onToggleLegendKey(key));

    expect(result.current.lensControl.hiddenLegendKeys).toEqual([key]);
    expect(result.current.overlayControls.anyLegendHidden).toBe(true);
    act(() => vi.advanceTimersByTime(399));
    expect(result.current.look.hiddenLegendKeys.axis_ramp).toBeUndefined();
    act(() => vi.advanceTimersByTime(1));
    expect(result.current.look.hiddenLegendKeys.axis_ramp).toEqual([key]);
    const allKeys = result.current.lensControl.legend.map((entry) => entry.key);
    act(() => result.current.lensControl.onSetHiddenLegendKeys(allKeys));
    expect(result.current.lensControl.hiddenLegendKeys).toEqual(allKeys);

    act(() => result.current.overlayControls.onShowAllLegendRows());
    act(() => vi.advanceTimersByTime(400));
    expect(result.current.lensControl.hiddenLegendKeys).toEqual([]);
    expect(Object.values(result.current.look.hiddenLegendKeys).flat()).toEqual([]);
  });

  it("「絞り込みをすべて解除」が押せるのは地図に出しているものの凡例で隠している間だけで、出していないレイヤーの最初に隠す行は数えない", () => {
    serve();
    const { result } = render();
    expect(chip(result, "surface")).toMatchObject({ on: false, legendDetails: [{ hiddenKeys: [LEGEND_NO_DATA_KEY] }] });
    expect(result.current.overlayControls.anyLegendHidden).toBe(false);

    act(() => result.current.overlayControls.onToggle("surface", true));

    expect(result.current.overlayControls.anyLegendHidden).toBe(true);
  });

  it.each([
    { layer: "surface", row: "データなし（値の無い道が分からない属性）", key: LEGEND_NO_DATA_KEY },
    { layer: "cycleway", row: "該当なし（タグの不在が当てはまらない属性）", key: ROAD_OTHER_KEY },
  ])(
    "値の無い道の行を最初は隠す層（$layer）は、$rowを地図でも凡例でも隠して始め、凡例で出すと次に開いたときも出たまま",
    async ({ layer, key }) => {
      serve();
      const first = render();
      const hiddenOf = (result: { current: ReturnType<typeof useMapView> }) => ({
        legend: chip(result, layer)?.legendDetails?.[0].hiddenKeys,
        map: result.current.look.hiddenLegendKeys[layer],
      });
      expect(hiddenOf(first.result)).toEqual({ legend: [key], map: [key] });

      act(() => first.result.current.overlayControls.onLegendAxisSetHidden(layer, []));
      first.unmount();

      const { result } = render();
      await waitFor(() => expect(hiddenOf(result)).toEqual({ legend: [], map: [] }));
    },
  );

  it("災害のチップの凡例で隠した情報は描かず、絞り込み中に数える", () => {
    serve();
    const { result } = render();

    act(() => result.current.overlayControls.onLegendEntryToggle("disaster", "heavyRain"));

    expect(result.current.look.dynamicWeather.disaster?.heavyRain?.visible).toBe(false);
    expect(result.current.look.dynamicWeather.disaster?.landslide?.visible).toBe(true);
    expect(result.current.overlayControls.anyLegendHidden).toBe(true);
    expect(chip(result, "disaster")?.legendDetails?.[0].hiddenKeys).toEqual(["heavyRain"]);
  });

  it("表示・レンズ・周りを塗る設定・隠した行は、次に開いたときも残る", async () => {
    serve();
    const first = render();
    await waitFor(() => expect(first.result.current.lensControl.axisOptions).toHaveLength(1));
    act(() => first.result.current.overlayControls.onToggle("hillshade", true));
    act(() => first.result.current.lensControl.onLensChange("axis_ramp"));
    act(() => first.result.current.lensControl.onKeepAfterRouteChange(false));
    act(() => first.result.current.overlayControls.onLegendEntryToggle("disaster", "heavyRain"));
    first.unmount();

    const { result } = render();

    await waitFor(() => expect(result.current.lensControl.lens).toBe("axis_ramp"));
    expect(result.current.look.layerVisibility.hillshade).toBe(true);
    expect(result.current.lensControl.keepAfterRoute).toBe(false);
    expect(chip(result, "disaster")?.legendDetails?.[0].hiddenKeys).toEqual(["heavyRain"]);
  });

  it("表示中のレイヤーをすべて非表示にすると一覧の行だけを消してルートは残し、地図へは中身が変わるか再描画を頼んだときだけ新しい値を渡す", () => {
    serve();
    const { result, rerender } = render();
    expect(result.current.overlayControls.layers.some((layer) => layer.on)).toBe(true);
    expect(result.current.look.layerVisibility.route).toBe(true);

    act(() => result.current.overlayControls.onHideAllLayers());

    expect(result.current.overlayControls.layers.filter((layer) => layer.on)).toEqual([]);
    expect(result.current.look.layerVisibility.route).toBe(true);
    const look = result.current.look;
    rerender({});
    expect(result.current.look).toBe(look);
    act(() => result.current.redrawMap());
    expect(result.current.look).toMatchObject({ ...look, refreshToken: 1 });
  });

  it("チップには、地図から上がる取得の状態と気象の取得の状態を合わせ、表示範囲のズームで出ないレイヤーに案内を出す", async () => {
    serve();
    const { result } = render();

    act(() => result.current.look.onLayerDataStatusChange({ surface: "loading" }));
    act(() => result.current.look.onViewportChange({ ...VIEWPORT, zoom: 8 }));

    expect(chip(result, "surface")).toMatchObject({ dataStatus: "loading", notice: TILE_ZOOM_TOO_WIDE_NOTICE });
    expect(chip(result, "hillshade")?.notice).toBeNull();
    await waitFor(() => expect(chip(result, "disaster")?.dataStatus).toBe("empty"));
  });

  it.each([
    { name: "世代を持たない応答", catalog: () => Response.json(catalogResponse([])) },
    { name: "取得の失敗", catalog: () => new HttpResponse(null, { status: 500 }) },
  ])(
    "タイルの世代で描くレイヤーは、軸カタログが届くまで読み込み中、届いても世代が無ければ失敗にする（$name）",
    async ({ catalog }) => {
      serve(catalog());

      const { result } = render();

      expect(chip(result, "surface")?.dataStatus).toBe("loading");
      await waitFor(() => expect(chip(result, "surface")?.dataStatus).toBe("error"));
      expect(chip(result, "surface")?.notice).toBe(TILE_VERSIONS_MISSING_NOTICE);
    },
  );

  it("ルートの出し入れは色分けが持ち、候補を選ぶまで押せない", () => {
    serve();
    const { result, rerender } = render();
    expect(result.current.lensControl).toMatchObject({ routeShown: true, routeSelectable: false });

    rerender({ hasSelectedRoute: true });
    act(() => result.current.lensControl.onRouteShownChange(false));

    expect(result.current.lensControl).toMatchObject({ routeShown: false, routeSelectable: true });
    expect(result.current.look.layerVisibility.route).toBe(false);
  });
});

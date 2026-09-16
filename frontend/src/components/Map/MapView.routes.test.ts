// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { RouteCandidate } from "@/types/route";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import {
  ROAD_INSPECT_LAYER_ID,
  computeRouteFitPadding,
  computeRouteBounds,
  redrawAllLayers,
  type RedrawAllLayersProps,
} from "./MapView";
import {
  OUTLINE_LAYER_ID,
  ROUTES_LAYER_ID,
  ROUTE_ARROW_HALO_LAYER_ID,
  ROUTE_ARROW_LAYER_ID,
  SPLICED_ROUTE_LAYER_ID,
  SPLICE_LAYER_ID,
  applyRouteLayerVisibility,
  drawBaseRoutes,
  drawSelectedOutline,
  hideBaseRoutes,
  hideSelectedOutline,
  routesToFeatureCollection,
} from "./MapView.routes";

const makeCandidate = makeRouteCandidate;

describe("routesToFeatureCollection", () => {
  it("選択中の候補が配列の最後（最前面）に描画されるよう並び替える", () => {
    const a = makeCandidate({ id: "a" });
    const b = makeCandidate({ id: "b" });
    const c = makeCandidate({ id: "c" });

    const collection = routesToFeatureCollection([a, b, c], "b");

    expect(collection.features.map((f) => f.properties.selected)).toEqual([false, false, true]);
    // bが最後（最前面）に来ている
    expect(collection.type).toBe("FeatureCollection");
    const lastFeature = collection.features[collection.features.length - 1];
    expect(lastFeature.properties.selected).toBe(true);
  });

  it("選択中の候補が無い場合は全区間selected:falseのまま順序も変わらない", () => {
    const a = makeCandidate({ id: "a" });
    const b = makeCandidate({ id: "b" });

    const collection = routesToFeatureCollection([a, b], null);

    expect(collection.features.map((f) => f.properties.selected)).toEqual([false, false]);
  });

  it("各featureのgeometryは候補のgeometryをそのまま使う", () => {
    const geometry: GeoJSON.LineString = {
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.71, 35.71],
      ],
    };
    const collection = routesToFeatureCollection([makeCandidate({ id: "a", geometry })], "a");

    expect(collection.features[0].geometry).toEqual(geometry);
  });

  it("候補が0件ならfeaturesも空配列", () => {
    const collection = routesToFeatureCollection([], null);

    expect(collection.features).toEqual([]);
  });
});

describe("computeRouteBounds", () => {
  it("全候補の形状点を包含するboundsを返す", () => {
    const routes = [
      makeCandidate({
        id: "a",
        geometry: {
          type: "LineString",
          coordinates: [
            [139.7, 35.7],
            [139.72, 35.72],
          ],
        },
      }),
      makeCandidate({
        id: "b",
        geometry: {
          type: "LineString",
          coordinates: [
            [139.68, 35.68],
            [139.75, 35.75],
          ],
        },
      }),
    ];

    const bounds = computeRouteBounds(routes);

    // 全候補中の最小/最大経緯度を包含している
    expect(bounds.getWest()).toBeCloseTo(139.68);
    expect(bounds.getEast()).toBeCloseTo(139.75);
    expect(bounds.getSouth()).toBeCloseTo(35.68);
    expect(bounds.getNorth()).toBeCloseTo(35.75);
  });

  it("候補が0件でも空のboundsを返す（例外を投げない）", () => {
    const bounds = computeRouteBounds([]);

    expect(bounds.isEmpty()).toBe(true);
  });
});

// 改善計画T518: 地図上の「ルート」チップ（layerVisibility.route）をOFFにしたとき、
// 候補線（route-candidates-line）・選択中候補のハロー（route-selected-outline-line）・
// 方向矢印（route-arrow-halo/route-arrow）の3レイヤーグループすべてが非表示になることの
// 検証。__rcStyleReady=trueでrunWhenStyleReadyの即時実行分岐を通す
// （MapView.layerOps.test.tsと同じfakeMapパターン、setLayoutPropertyの呼び出しを追加）。
function fakeMap() {
  const layers = new Set<string>();
  const sources = new Set<string>();
  const layoutCalls: { layerId: string; name: string; value: unknown }[] = [];
  const setDataCalls: unknown[] = [];
  const fitBoundsCalls: unknown[] = [];
  const filterCalls: { layerId: string; filter: unknown }[] = [];
  return {
    __rcStyleReady: true,
    layers,
    sources,
    layoutCalls,
    setDataCalls,
    filterCalls,
    getLayer: (id: string) => (layers.has(id) ? {} : undefined),
    addLayer: (spec: { id: string }) => layers.add(spec.id),
    getSource: (id: string) => (sources.has(id) ? { setData: (data: unknown) => setDataCalls.push(data) } : undefined),
    addSource: (id: string) => sources.add(id),
    // ensureRouteArrowLayerが矢印アイコンの新規作成（document.createElement("canvas")、
    // node環境のこのテストファイルではDOM APIが無い）に入らないよう、常時「登録済み」を
    // 返して分岐をスキップさせる（アイコン画像自体の生成ロジックはこのテストの検証対象外）。
    hasImage: () => true,
    addImage: () => {},
    setLayoutProperty: (layerId: string, name: string, value: unknown) => layoutCalls.push({ layerId, name, value }),
    // 再描画の入口（redrawAllLayers）を通すぶんだけ、地図側の受け口を足す。
    fitBoundsCalls,
    fitBounds: (...args: unknown[]) => fitBoundsCalls.push(args),
    getZoom: () => 14,
    getCanvas: () => ({ clientWidth: 390, clientHeight: 812 }),
    setPaintProperty: () => {},
    setFilter: (layerId: string, filter: unknown) => filterCalls.push({ layerId, filter }),
    setFeatureState: () => {},
    removeFeatureState: () => {},
  };
}

function layoutValue(map: ReturnType<typeof fakeMap>, layerId: string, name: string): unknown {
  const call = [...map.layoutCalls].reverse().find((c) => c.layerId === layerId && c.name === name);
  return call?.value;
}

function makeRoute(id: string): RouteCandidate {
  return makeRouteCandidate({ id, direction_label: "北", distance_km: 15 });
}

describe("drawBaseRoutes/hideBaseRoutes（「ルート」チップの表示切替、改善計画T518）", () => {
  it("新規作成時にROUTES_LAYER_IDをvisibleにする", () => {
    const map = fakeMap();
    const routes = [makeRoute("a")];

    drawBaseRoutes(map as unknown as Parameters<typeof drawBaseRoutes>[0], routes, "a");

    expect(layoutValue(map, ROUTES_LAYER_ID, "visibility")).toBe("visible");
  });

  it("hideBaseRoutesはROUTES_LAYER_IDをnoneにする", () => {
    const map = fakeMap();
    map.addLayer({ id: ROUTES_LAYER_ID });

    hideBaseRoutes(map as unknown as Parameters<typeof hideBaseRoutes>[0]);

    expect(layoutValue(map, ROUTES_LAYER_ID, "visibility")).toBe("none");
  });

  it(
    "既存sourceがある状態（2回目以降の描画）でもvisibility=visibleを明示する" +
      "（hideBaseRoutesでnoneにした後、再度ONにしたときに再表示されるようにするため）",
    () => {
      const map = fakeMap();
      const routes = [makeRoute("a")];
      drawBaseRoutes(map as unknown as Parameters<typeof drawBaseRoutes>[0], routes, "a");
      map.layoutCalls.length = 0; // 初回描画分をクリアして2回目のみ検証する

      drawBaseRoutes(map as unknown as Parameters<typeof drawBaseRoutes>[0], routes, "a");

      expect(layoutValue(map, ROUTES_LAYER_ID, "visibility")).toBe("visible");
    },
  );
});

describe("drawSelectedOutline/hideSelectedOutline（「ルート」チップの表示切替、改善計画T518）", () => {
  it("新規作成時にハロー・矢印ハロー・矢印の3レイヤーをすべてvisibleにする", () => {
    const map = fakeMap();
    const routes = [makeRoute("a")];

    drawSelectedOutline(map as unknown as Parameters<typeof drawSelectedOutline>[0], routes, "a");

    expect(layoutValue(map, OUTLINE_LAYER_ID, "visibility")).toBe("visible");
    expect(layoutValue(map, ROUTE_ARROW_HALO_LAYER_ID, "visibility")).toBe("visible");
    expect(layoutValue(map, ROUTE_ARROW_LAYER_ID, "visibility")).toBe("visible");
  });

  it("hideSelectedOutlineは3レイヤーすべてをnoneにする", () => {
    const map = fakeMap();
    map.addLayer({ id: OUTLINE_LAYER_ID });
    map.addLayer({ id: ROUTE_ARROW_HALO_LAYER_ID });
    map.addLayer({ id: ROUTE_ARROW_LAYER_ID });

    hideSelectedOutline(map as unknown as Parameters<typeof hideSelectedOutline>[0]);

    expect(layoutValue(map, OUTLINE_LAYER_ID, "visibility")).toBe("none");
    expect(layoutValue(map, ROUTE_ARROW_HALO_LAYER_ID, "visibility")).toBe("none");
    expect(layoutValue(map, ROUTE_ARROW_LAYER_ID, "visibility")).toBe("none");
  });

  it("既存source（2回目以降の描画）でも3レイヤーすべてへvisibility=visibleを明示する", () => {
    const map = fakeMap();
    const routes = [makeRoute("a")];
    drawSelectedOutline(map as unknown as Parameters<typeof drawSelectedOutline>[0], routes, "a");
    map.layoutCalls.length = 0;

    drawSelectedOutline(map as unknown as Parameters<typeof drawSelectedOutline>[0], routes, "a");

    expect(layoutValue(map, OUTLINE_LAYER_ID, "visibility")).toBe("visible");
    expect(layoutValue(map, ROUTE_ARROW_HALO_LAYER_ID, "visibility")).toBe("visible");
    expect(layoutValue(map, ROUTE_ARROW_LAYER_ID, "visibility")).toBe("visible");
  });
});

// 改善計画T524（T518コードレビューP1指摘の修正）: redrawAllLayers（地図データ再読み込み・
// map.setStyle()後の再描画）と2つのuseEffectが、以前は個別にif(routeLayerOn)分岐を
// 手書きしていたため、redrawAllLayersだけrouteLayerOnを見ずに無条件でdrawBaseRoutes/
// drawSelectedOutlineを呼ぶ実装漏れが発生していた（「ルート」チップOFFで隠した候補線・
// ハロー・矢印が、地図データ再読み込みで復活するバグ）。3箇所を1つの共有関数
// applyRouteLayerVisibilityへ集約した——ここではその共有関数自体を検証する。
describe("applyRouteLayerVisibility（「ルート」チップの表示切替を1箇所へ集約、改善計画T524）", () => {
  it("routeLayerOn=trueなら候補線・ハロー・矢印ハロー・矢印の4レイヤーすべてをvisibleにする", () => {
    const map = fakeMap();
    const routes = [makeRoute("a")];

    applyRouteLayerVisibility(map as unknown as Parameters<typeof applyRouteLayerVisibility>[0], true, routes, "a");

    expect(layoutValue(map, ROUTES_LAYER_ID, "visibility")).toBe("visible");
    expect(layoutValue(map, OUTLINE_LAYER_ID, "visibility")).toBe("visible");
    expect(layoutValue(map, ROUTE_ARROW_HALO_LAYER_ID, "visibility")).toBe("visible");
    expect(layoutValue(map, ROUTE_ARROW_LAYER_ID, "visibility")).toBe("visible");
  });

  it("routeLayerOn=falseなら4レイヤーすべてをnoneにする（既にレイヤーが存在する状態から）", () => {
    const map = fakeMap();
    const routes = [makeRoute("a")];
    map.addLayer({ id: ROUTES_LAYER_ID });
    map.addLayer({ id: OUTLINE_LAYER_ID });
    map.addLayer({ id: ROUTE_ARROW_HALO_LAYER_ID });
    map.addLayer({ id: ROUTE_ARROW_LAYER_ID });

    applyRouteLayerVisibility(map as unknown as Parameters<typeof applyRouteLayerVisibility>[0], false, routes, "a");

    expect(layoutValue(map, ROUTES_LAYER_ID, "visibility")).toBe("none");
    expect(layoutValue(map, OUTLINE_LAYER_ID, "visibility")).toBe("none");
    expect(layoutValue(map, ROUTE_ARROW_HALO_LAYER_ID, "visibility")).toBe("none");
    expect(layoutValue(map, ROUTE_ARROW_LAYER_ID, "visibility")).toBe("none");
  });

  // ここが見るのは`applyRouteLayerVisibility`単体の冪等性だけ。再描画経路を通したときの
  // 挙動は下の`redrawAllLayers`のdescribeが実物を呼んで見る。
  it("routeLayerOn=falseのまま呼び直してもnoneのまま（同じ入力で呼び直しても状態が反転しない）", () => {
    const map = fakeMap();
    const routes = [makeRoute("a")];
    applyRouteLayerVisibility(map as unknown as Parameters<typeof applyRouteLayerVisibility>[0], true, routes, "a");
    applyRouteLayerVisibility(map as unknown as Parameters<typeof applyRouteLayerVisibility>[0], false, routes, "a");
    map.layoutCalls.length = 0;

    // 「ルート」チップOFFのまま地図データ再読み込みが起きた想定でもう一度false呼び出し
    applyRouteLayerVisibility(map as unknown as Parameters<typeof applyRouteLayerVisibility>[0], false, routes, "a");

    expect(layoutValue(map, ROUTES_LAYER_ID, "visibility")).toBe("none");
    expect(layoutValue(map, OUTLINE_LAYER_ID, "visibility")).toBe("none");
  });

  it("routeLayerOn=falseで隠した後、再度trueで呼ぶとvisibleへ戻る", () => {
    const map = fakeMap();
    const routes = [makeRoute("a")];
    applyRouteLayerVisibility(map as unknown as Parameters<typeof applyRouteLayerVisibility>[0], true, routes, "a");
    applyRouteLayerVisibility(map as unknown as Parameters<typeof applyRouteLayerVisibility>[0], false, routes, "a");
    map.layoutCalls.length = 0;

    applyRouteLayerVisibility(map as unknown as Parameters<typeof applyRouteLayerVisibility>[0], true, routes, "a");

    expect(layoutValue(map, ROUTES_LAYER_ID, "visibility")).toBe("visible");
    expect(layoutValue(map, OUTLINE_LAYER_ID, "visibility")).toBe("visible");
  });
});

describe("computeRouteFitPadding", () => {
  const canvas = { width: 390, height: 812 };

  it("覆いが無ければ全辺が基本余白のまま", () => {
    expect(computeRouteFitPadding(undefined, canvas)).toEqual({ top: 40, bottom: 40, left: 40, right: 40 });
  });

  it("覆われている高さが該当する辺の余白へ足される", () => {
    // モバイルの下部タブバー(56px)＋シート50vh(406px)に覆われている想定
    expect(computeRouteFitPadding({ bottom: 462 }, canvas)).toEqual({ top: 40, bottom: 502, left: 40, right: 40 });
  });

  it("対向する2辺が地図の高さを食い尽くす場合は可視領域が残るまで縮める", () => {
    // 覆い800px + 基本余白40px*2 = 880pxは高さ812pxを超える
    const padding = computeRouteFitPadding({ bottom: 800 }, canvas);

    expect(padding.top + padding.bottom).toBeCloseTo(812 - 80);
    // 縮めても上下の比率（40 : 840）は保つ
    expect(padding.bottom / padding.top).toBeCloseTo(840 / 40);
  });

  it("横方向も同じ規則で縮める", () => {
    const padding = computeRouteFitPadding({ left: 400, right: 400 }, canvas);

    expect(padding.left + padding.right).toBeCloseTo(390 - 80);
    expect(padding.left).toBeCloseTo(padding.right);
  });
});

describe("候補featureのproperties（地図から候補を選ぶための識別子）", () => {
  it("各featureに候補idを載せる（ROUTES_HIT_LAYER_IDのクリックがこれで候補を特定する）", () => {
    const collection = routesToFeatureCollection([makeCandidate({ id: "a" }), makeCandidate({ id: "b" })], "a");

    expect(collection.features.map((f) => f.properties.routeId).sort()).toEqual(["a", "b"]);
  });
});

// map.setStyle()はカスタムのsource/layerを全て捨てるため、その後の作り直しが対象を
// 取りこぼすと、そのレイヤーは押した人の地図から消えたまま戻らない。ここは共有関数を
// 単体で見るのではなく、再描画の入口（redrawAllLayers）そのものを呼んで確かめる。
// 「新設した描画がここから辿れるか」自体はscripts/review_checks.pyのmap_redraw_coverageが
// 機械的に落とす——このテストは辿れた先が実際に作り直されることを見る。
describe("redrawAllLayers（map.setStyle()後の作り直し）", () => {
  const stretch = {
    index: 0,
    taken: false,
    coordinates: [
      [139.7, 35.7],
      [139.71, 35.7],
    ] as GeoJSON.Position[],
  };

  function redrawProps(overrides: Partial<RedrawAllLayersProps> = {}): RedrawAllLayersProps {
    return {
      routes: [],
      selectedRouteId: null,
      routeLayerOn: true,
      routeStyleModes: [],
      routeStyleModeId: "none",
      hiddenRouteLegendKeys: [],
      spliceStretches: undefined,
      splicedRoute: null,
      staticLayerVisibility: {} as RedrawAllLayersProps["staticLayerVisibility"],
      dynamicWeather: {},
      dedicatedWayValueVisibility: {},
      axisVisibility: {},
      roadHiddenKeysByMode: {} as RedrawAllLayersProps["roadHiddenKeysByMode"],
      staticLegendHiddenKeysByAxis: {} as RedrawAllLayersProps["staticLegendHiddenKeysByAxis"],
      experimentSlots: [],
      staticOverlayLayers: [],
      staticFilterAxes: [],
      dedicatedWayValues: new Map(),
      inspectedWayId: null,
      ...overrides,
    };
  }

  function redraw(map: ReturnType<typeof fakeMap>, overrides: Partial<RedrawAllLayersProps> = {}) {
    redrawAllLayers(map as unknown as Parameters<typeof redrawAllLayers>[0], redrawProps(overrides));
  }

  it("合成ルートを表示中に作り直すと、乗り換え区間の帯と編集中の線も戻る", () => {
    // 帯は候補線とは別のsourceを持つ。作り直しの対象から落ちると橙色の帯が消えたまま戻らない。
    const map = fakeMap();

    redraw(map, {
      routes: [makeRoute("a")],
      selectedRouteId: "a",
      spliceStretches: [stretch],
      splicedRoute: stretch.coordinates,
    });

    expect(layoutValue(map, SPLICE_LAYER_ID, "visibility")).toBe("visible");
    expect(layoutValue(map, SPLICED_ROUTE_LAYER_ID, "visibility")).toBe("visible");
    expect(layoutValue(map, ROUTES_LAYER_ID, "visibility")).toBe("visible");
  });

  // 強調はレイヤーのfilterとvisibilityで持つため、setStyle()でソースごと消えると初期値へ
  // 戻る。ポップアップは開いたままなので、復元しないと「どの線の話か」だけが失われる
  // （T524・T825と同じ型の欠陥）。
  it("道の詳細を開いたまま作り直すと、その道の強調も戻る", () => {
    const map = fakeMap();
    map.addLayer({ id: ROAD_INSPECT_LAYER_ID });

    redraw(map, { inspectedWayId: 156167860 });

    expect(layoutValue(map, ROAD_INSPECT_LAYER_ID, "visibility")).toBe("visible");
    expect(map.filterCalls.at(-1)).toEqual({
      layerId: ROAD_INSPECT_LAYER_ID,
      filter: ["==", ["get", "osm_way_id"], 156167860],
    });
  });

  it("道の詳細を開いていなければ、作り直しても強調は出ない", () => {
    const map = fakeMap();
    map.addLayer({ id: ROAD_INSPECT_LAYER_ID });

    redraw(map, { inspectedWayId: null });

    expect(layoutValue(map, ROAD_INSPECT_LAYER_ID, "visibility")).toBe("none");
  });

  it("「ルート」チップOFFのまま作り直しても、帯・合成ルート・候補線は出てこない", () => {
    const map = fakeMap();

    redraw(map, {
      routes: [makeRoute("a")],
      selectedRouteId: "a",
      routeLayerOn: false,
      spliceStretches: [stretch],
      splicedRoute: stretch.coordinates,
    });

    // 隠す側はレイヤーを作らない（setStyle()直後の地図には存在しないため、
    // visibility=noneの指定すら発生しない）。
    expect(map.layers.has(SPLICE_LAYER_ID)).toBe(false);
    expect(map.layers.has(SPLICED_ROUTE_LAYER_ID)).toBe(false);
    expect(map.layers.has(ROUTES_LAYER_ID)).toBe(false);
  });

  it("カメラは動かさない（表示範囲は利用者の操作に属する）", () => {
    const map = fakeMap();

    redraw(map, { routes: [makeRoute("a")], selectedRouteId: "a" });

    expect(map.fitBoundsCalls).toHaveLength(0);
  });
});

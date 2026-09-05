// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { RouteCandidate } from "@/types/route";
import {
  OUTLINE_LAYER_ID,
  ROUTE_ARROW_HALO_LAYER_ID,
  ROUTE_ARROW_LAYER_ID,
  ROUTES_LAYER_ID,
  applyRouteLayerVisibility,
  computeRouteBounds,
  drawBaseRoutes,
  drawSelectedOutline,
  hideBaseRoutes,
  hideSelectedOutline,
  routesToFeatureCollection,
} from "./MapView";

function makeCandidate(overrides: Partial<RouteCandidate>): RouteCandidate {
  return {
    id: "candidate-0",
    direction_label: "0度",
    distance_km: 15,
    geometry: { type: "LineString", coordinates: [[139.7, 35.7]] },
    elevation_gain_m: 100,
    min_elevation_m: 0,
    max_elevation_m: 50,
    segments: null,
    overall_difficulty: 40,
    axis_difficulties: {},
    material_values: {},
    axis_contributions: {},
    ...overrides,
  };
}

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
            [139.70, 35.70],
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
  return {
    __rcStyleReady: true,
    layers,
    sources,
    layoutCalls,
    setDataCalls,
    getLayer: (id: string) => (layers.has(id) ? {} : undefined),
    addLayer: (spec: { id: string }) => layers.add(spec.id),
    getSource: (id: string) =>
      sources.has(id) ? { setData: (data: unknown) => setDataCalls.push(data) } : undefined,
    addSource: (id: string) => sources.add(id),
    // ensureRouteArrowLayerが矢印アイコンの新規作成（document.createElement("canvas")、
    // node環境のこのテストファイルではDOM APIが無い）に入らないよう、常時「登録済み」を
    // 返して分岐をスキップさせる（アイコン画像自体の生成ロジックはこのテストの検証対象外）。
    hasImage: () => true,
    addImage: () => {},
    setLayoutProperty: (layerId: string, name: string, value: unknown) => layoutCalls.push({ layerId, name, value }),
  };
}

function layoutValue(map: ReturnType<typeof fakeMap>, layerId: string, name: string): unknown {
  const call = [...map.layoutCalls].reverse().find((c) => c.layerId === layerId && c.name === name);
  return call?.value;
}

function makeRoute(id: string): RouteCandidate {
  return {
    id,
    direction_label: "0度",
    distance_km: 15,
    geometry: {
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.71, 35.71],
      ],
    },
    elevation_gain_m: 100,
    min_elevation_m: 0,
    max_elevation_m: 50,
    segments: null,
    overall_difficulty: 40,
    axis_difficulties: {},
    material_values: {},
    axis_contributions: {},
  };
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

  it("既存sourceがある状態（2回目以降の描画）でもvisibility=visibleを明示する" +
    "（hideBaseRoutesでnoneにした後、再度ONにしたときに再表示されるようにするため）", () => {
    const map = fakeMap();
    const routes = [makeRoute("a")];
    drawBaseRoutes(map as unknown as Parameters<typeof drawBaseRoutes>[0], routes, "a");
    map.layoutCalls.length = 0; // 初回描画分をクリアして2回目のみ検証する

    drawBaseRoutes(map as unknown as Parameters<typeof drawBaseRoutes>[0], routes, "a");

    expect(layoutValue(map, ROUTES_LAYER_ID, "visibility")).toBe("visible");
  });
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

  it("routeLayerOn=falseで隠した後、再度trueで呼ぶとvisibleへ戻す" +
    "（redrawAllLayers経由でも「ルート」チップOFFの状態を維持できることの直接的な検証）", () => {
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
});

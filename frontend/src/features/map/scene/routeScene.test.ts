// @vitest-environment node
/**
 * `routeScene.ts`——画面の状態からルートの scene を組み立てる純関数。
 *
 * ここでは見ないもの:
 * - 組み立てた scene を地図へ当てる差分計算 → `applyMapScene.test.ts`
 * - 段どうしの前後・押せるレイヤーの導出 → `mapScene.test.ts`
 * - 区間の色式そのもの（段の切り方・配色）——軸カタログ由来のため差し替えて与える
 */
import type { FilterSpecification } from "maplibre-gl";
import { describe, expect, it } from "vitest";

import { interactiveSceneLayerIds, orderedSceneLayers, type MapScene, type MapSceneLayer } from "./mapScene";
import {
  ROUTE_HIT_TARGET,
  ROUTE_SOURCE_IDS,
  buildRouteScene,
  routeSceneLayerId,
  type RouteLayerRole,
  type RoutePath,
  type RouteSceneState,
  type RouteSceneStyle,
} from "./routeScene";

const STYLE: RouteSceneStyle = {
  candidateColor: "#candidate",
  candidateWidthPx: 2,
  hitWidthPx: 20,
  selectedHaloColor: "#halo",
  selectedHaloWidthPx: 16,
  selectedHaloOpacity: 0.3,
  casingColor: "#casing",
  spliceBandColor: "#band",
  spliceBandWidthPx: 14,
  spliceBandOpacity: 0.5,
  compositeColor: "#composite",
  compositeWidthPx: 6,
  compositeCasingWidthPx: 10,
  comparisonSlotWidthPx: 3,
  comparisonSlotCasingWidthPx: 5,
  arrowSpacingPx: 120,
};

const PATH_A: RoutePath = [
  [139.7, 35.6],
  [139.8, 35.7],
];
const PATH_B: RoutePath = [
  [139.6, 35.5],
  [139.65, 35.55],
];

function stateWith(overrides: Partial<RouteSceneState> = {}): RouteSceneState {
  return {
    visible: true,
    candidates: [
      { routeId: "a", path: PATH_A, arrows: { iconImage: "cw", haloIconImage: "cw-halo" } },
      { routeId: "b", path: PATH_B },
    ],
    selectedRouteId: "a",
    segments: [{ path: PATH_A, properties: { band: 2 } }],
    coloring: { lineColor: ["get", "band"] },
    spliceBands: [],
    composite: null,
    comparisonSlots: [],
    style: STYLE,
    ...overrides,
  };
}

function layerById(scene: MapScene, role: RouteLayerRole): MapSceneLayer {
  const id = routeSceneLayerId(role);
  const found = scene.layers.find((layer) => layer.spec.id === id);
  if (found === undefined) throw new Error(`レイヤーが無い: ${id}`);
  return found;
}

function orderOf(scene: MapScene, role: RouteLayerRole): number {
  return orderedSceneLayers(scene).findIndex((layer) => layer.spec.id === routeSceneLayerId(role));
}

function paintOf(layer: MapSceneLayer): Record<string, unknown> {
  return (layer.spec as { paint?: Record<string, unknown> }).paint ?? {};
}

function dataOf(scene: MapScene, sourceId: string): { features: unknown[] } {
  const source = scene.sources.find((entry) => entry.id === sourceId);
  if (source === undefined) throw new Error(`ソースが無い: ${sourceId}`);
  return (source.content?.spec as { data: { features: unknown[] } }).data;
}

describe("buildRouteScene の重なり", () => {
  it("選択中候補は縁取り→色分け線→当たり判定→矢印ハロー→矢印の順に重なる", () => {
    const scene = buildRouteScene(stateWith());
    const roles: readonly RouteLayerRole[] = ["detailCasing", "detailLine", "detailHit", "arrowHalo", "arrow"];
    const order = roles.map((role) => orderOf(scene, role));
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(order.every((index) => index >= 0)).toBe(true);
  });

  it("帯の当たり判定は区間の当たり判定より前面にある", () => {
    // 区間の当たり判定はルート全体を覆うため、後ろに置くと帯が一度も押せない。
    const scene = buildRouteScene(stateWith({ spliceBands: [{ path: PATH_A }] }));
    expect(orderOf(scene, "spliceBandHit")).toBeGreaterThan(orderOf(scene, "detailHit"));
  });

  it("選択中候補のハローは候補の線より背面にある", () => {
    // 前へ出すと薄い暗色が線へかぶり、レンズの配色が濁る。
    const scene = buildRouteScene(stateWith());
    expect(orderOf(scene, "selectedHalo")).toBeLessThan(orderOf(scene, "candidateLine"));
  });

  it("比較スロットは参考線より前面・選択中候補の区間より背面にある", () => {
    // 参考線に埋もれると比較にならず、区間より前へ出るといま見ている候補を隠す。
    const scene = buildRouteScene(stateWith({ comparisonSlots: [{ slotId: "s1", path: PATH_B, color: "#slot" }] }));
    for (const role of ["comparisonSlotCasing", "comparisonSlotLine"] as const) {
      expect(orderOf(scene, role)).toBeGreaterThan(orderOf(scene, "candidateLine"));
      expect(orderOf(scene, role)).toBeLessThan(orderOf(scene, "detailCasing"));
    }
  });

  it("参考線は選択中候補の色分け線より背面にある", () => {
    const scene = buildRouteScene(stateWith());
    expect(orderOf(scene, "candidateLine")).toBeLessThan(orderOf(scene, "detailLine"));
  });

  it("宣言の順のまま返り、当てる側の並べ替えに依存しない", () => {
    const scene = buildRouteScene(stateWith());
    expect(scene.layers.map((layer) => layer.spec.id)).toEqual(orderedSceneLayers(scene).map((layer) => layer.spec.id));
  });
});

describe("buildRouteScene の当たり判定", () => {
  it("押せるレイヤーは透明で、見えるレイヤーは押せない", () => {
    const scene = buildRouteScene(stateWith({ spliceBands: [{ path: PATH_B }] }));
    for (const layer of scene.layers) {
      const opacity = paintOf(layer)["line-opacity"];
      if (layer.hitTargets.length > 0) expect(opacity).toBe(0);
      else expect(opacity).not.toBe(0);
    }
  });

  it("押せるレイヤーはすべてルートの当たり判定としても名乗る", () => {
    const scene = buildRouteScene(stateWith({ spliceBands: [{ path: PATH_B }] }));
    const interactive = interactiveSceneLayerIds(scene);
    expect(interactive.length).toBeGreaterThan(0);
    for (const layer of scene.layers) {
      if (layer.hitTargets.length === 0) continue;
      expect(layer.hitTargets).toContain(ROUTE_HIT_TARGET);
    }
  });

  it("参考線の地物は、押された候補を見分ける値を持つ", () => {
    const scene = buildRouteScene(stateWith({ selectedRouteId: null, segments: [] }));
    expect(dataOf(scene, ROUTE_SOURCE_IDS.candidates).features).toEqual([
      expect.objectContaining({ properties: { routeId: "a" } }),
      expect.objectContaining({ properties: { routeId: "b" } }),
    ]);
  });
});

describe("buildRouteScene の候補と区間", () => {
  it("区間を描いている候補は参考線から外れる", () => {
    const scene = buildRouteScene(stateWith());
    expect(dataOf(scene, ROUTE_SOURCE_IDS.candidates).features).toEqual([
      expect.objectContaining({ properties: { routeId: "b" } }),
    ]);
  });

  it("区間がまだ無い間は選択中候補も参考線に残る", () => {
    const scene = buildRouteScene(stateWith({ segments: [] }));
    expect(dataOf(scene, ROUTE_SOURCE_IDS.candidates).features).toHaveLength(2);
  });

  it("矢印は選択中候補の地物から絵を読み、向きを持たない候補では絵が載らない", () => {
    const withArrows = buildRouteScene(stateWith());
    expect(dataOf(withArrows, ROUTE_SOURCE_IDS.selected).features).toEqual([
      expect.objectContaining({
        properties: { routeId: "a", arrowIcon: "cw", arrowHaloIcon: "cw-halo" },
      }),
    ]);

    const withoutArrows = buildRouteScene(stateWith({ selectedRouteId: "b", segments: [] }));
    expect(dataOf(withoutArrows, ROUTE_SOURCE_IDS.selected).features).toEqual([
      expect.objectContaining({ properties: { routeId: "b" } }),
    ]);
  });

  it("矢印2層は衝突判定を無効にする", () => {
    const scene = buildRouteScene(stateWith());
    const roles: readonly RouteLayerRole[] = ["arrowHalo", "arrow"];
    for (const role of roles) {
      const layout = (layerById(scene, role).spec as { layout: Record<string, unknown> }).layout;
      expect(layout["icon-allow-overlap"]).toBe(true);
      expect(layout["icon-ignore-placement"]).toBe(true);
    }
  });
});

describe("buildRouteScene の色分け", () => {
  it("凡例で隠した段の絞り込みは色分け線・縁取り・当たり判定の3枚だけへ載る", () => {
    const filter: FilterSpecification = ["!=", ["get", "band"], 3];
    const scene = buildRouteScene(stateWith({ coloring: { lineColor: "#x", hiddenBandFilter: filter } }));
    const filtered = scene.layers.filter((layer) => layer.filter !== undefined).map((layer) => layer.spec.id);
    const expected: readonly RouteLayerRole[] = ["detailCasing", "detailLine", "detailHit"];
    expect(filtered).toEqual(expected.map(routeSceneLayerId));
    for (const id of filtered) {
      const layer = scene.layers.find((entry) => entry.spec.id === id);
      expect(layer?.filter).toBe(filter);
    }
  });

  it("絞り込みが無い状態では、どのレイヤーも絞り込みを持たない", () => {
    const scene = buildRouteScene(stateWith());
    expect(scene.layers.every((layer) => layer.filter === undefined)).toBe(true);
  });

  it("縁取りはレンズの配色に依存せず、どの線の縁も同じ色になる", () => {
    const scene = buildRouteScene(
      stateWith({
        coloring: { lineColor: ["get", "band"] },
        composite: { path: PATH_A },
        comparisonSlots: [{ slotId: "s1", path: PATH_B, color: "#slot" }],
      }),
    );
    const casingRoles: readonly RouteLayerRole[] = ["detailCasing", "compositeCasing", "comparisonSlotCasing"];
    const casings = casingRoles.map((role) => paintOf(layerById(scene, role))["line-color"]);
    expect(new Set(casings)).toEqual(new Set([STYLE.casingColor]));
  });

  it("比較スロットの線はスロットごとの色を地物から読む", () => {
    const scene = buildRouteScene(
      stateWith({
        comparisonSlots: [
          { slotId: "s1", path: PATH_A, color: "#one" },
          { slotId: "s2", path: PATH_B, color: "#two" },
        ],
      }),
    );
    expect(paintOf(layerById(scene, "comparisonSlotLine"))["line-color"]).toEqual(["get", "color"]);
    expect(dataOf(scene, ROUTE_SOURCE_IDS.comparisonSlots).features).toEqual([
      expect.objectContaining({ properties: { slotId: "s1", color: "#one" } }),
      expect.objectContaining({ properties: { slotId: "s2", color: "#two" } }),
    ]);
  });
});

describe("buildRouteScene の表示と再現性", () => {
  it("ルートを出さない間もレイヤーは残り、表示だけが落ちる", () => {
    const hidden = buildRouteScene(stateWith({ visible: false }));
    const shown = buildRouteScene(stateWith());
    expect(hidden.layers.map((layer) => layer.spec.id)).toEqual(shown.layers.map((layer) => layer.spec.id));
    expect(hidden.layers.every((layer) => !layer.visible)).toBe(true);
  });

  it("空の状態でもソースは揃い、id は重複しない", () => {
    const scene = buildRouteScene(stateWith({ candidates: [], selectedRouteId: null, segments: [] }));
    expect(scene.sources.map((source) => source.id).sort()).toEqual(Object.values(ROUTE_SOURCE_IDS).slice().sort());
    const layerIds = scene.layers.map((layer) => layer.spec.id);
    expect(new Set(layerIds).size).toBe(layerIds.length);
    for (const source of scene.sources) {
      expect(dataOf(scene, source.id).features).toEqual([]);
    }
  });

  it("同じ入力からは同じ scene が出る", () => {
    const state = stateWith({
      spliceBands: [{ path: PATH_B, properties: { counterpartRouteId: "b" } }],
      composite: { path: PATH_A },
      comparisonSlots: [{ slotId: "s1", path: PATH_B, color: "#slot" }],
    });
    const first = buildRouteScene(state);
    const second = buildRouteScene(state);
    expect(JSON.stringify(second.layers)).toEqual(JSON.stringify(first.layers));
    expect(second.sources.map((source) => [source.id, source.content?.spec])).toEqual(
      first.sources.map((source) => [source.id, source.content?.spec]),
    );
  });

  it("入力を書き換えても、組み立て済みの scene は変わらない", () => {
    const candidates = [{ routeId: "a", path: PATH_A }];
    const scene = buildRouteScene(stateWith({ candidates, selectedRouteId: "a", segments: [] }));
    candidates.push({ routeId: "c", path: PATH_B });
    expect(dataOf(scene, ROUTE_SOURCE_IDS.candidates).features).toHaveLength(1);
  });
});

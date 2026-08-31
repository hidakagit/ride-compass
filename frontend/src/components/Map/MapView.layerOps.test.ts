// 改善計画T490: MapView.tsxのカバレッジ監査（2026-08-31）で発見された、docs/modules/
// frontend/static-map-layers.md・map-axis-coloring.mdが「暗黙の前提」として明記する
// 重要ロジックのうち、exportされておらずテスト対象から漏れていた関数群の単体テスト。
// MapView.overlayFilters.test.tsと同じ「実際のMapLibre Mapが必要とするメソッドだけを
// 持つフェイク」パターンを使う。
import { describe, expect, it } from "vitest";
import { KNOWN_LINE_OPACITY } from "@/components/Map/roadFilterAxes";
import {
  DEFAULT_ROAD_LINE_WIDTH,
  DESIGNATION_LAYER_ID,
  MATERIAL_TRACK_OFFSET_STEP,
  ONEWAY_LAYER_ID,
  ROAD_MATERIAL_TRACK_LAYER_IDS,
  ROAD_TILE_LAYER_ID,
  ROAD_TILE_SOURCE_ID,
  ROAD_TILE_SOURCE_LAYER,
  SECONDARY_AXIS_CASING_OPACITY,
  SECONDARY_AXIS_CASING_WIDTH,
  TUNNEL_LAYER_ID,
  applyAxisFeatureStateValues,
  applyRoadMaterialTrackOffsets,
  applySecondaryAxisCasingStyles,
  clearRoadTileFeatureState,
  shouldClearDedicatedWayValueFeatureState,
} from "./MapView";

// __rcStyleReady=trueでrunWhenStyleReadyの即時実行分岐を通す
// （MapView.overlayFilters.test.ts/MapView.dataStatus.test.tsと同じ発想）。
function fakeMap() {
  const layers = new Set<string>();
  const sources = new Set<string>();
  const paintCalls: { layerId: string; name: string; value: unknown }[] = [];
  const setFeatureStateCalls: { target: unknown; state: unknown }[] = [];
  const removeFeatureStateCalls: { target: unknown }[] = [];
  return {
    __rcStyleReady: true,
    layers,
    sources,
    paintCalls,
    setFeatureStateCalls,
    removeFeatureStateCalls,
    getLayer: (id: string) => (layers.has(id) ? {} : undefined),
    addLayer: (spec: { id: string }) => layers.add(spec.id),
    getSource: (id: string) => (sources.has(id) ? {} : undefined),
    addSource: (id: string) => sources.add(id),
    setPaintProperty: (layerId: string, name: string, value: unknown) => paintCalls.push({ layerId, name, value }),
    setFeatureState: (target: unknown, state: unknown) => setFeatureStateCalls.push({ target, state }),
    removeFeatureState: (target: unknown) => removeFeatureStateCalls.push({ target }),
  };
}

function paintValue(map: ReturnType<typeof fakeMap>, layerId: string, name: string): unknown {
  const call = [...map.paintCalls].reverse().find((c) => c.layerId === layerId && c.name === name);
  return call?.value;
}

describe("applyRoadMaterialTrackOffsets（並列トラック分離、改善計画T490）", () => {
  it("ONが1件だけならoffsetは0（並列に分ける相手がいない）", () => {
    const map = fakeMap();
    for (const id of ROAD_MATERIAL_TRACK_LAYER_IDS) map.addLayer({ id });

    applyRoadMaterialTrackOffsets(map as unknown as Parameters<typeof applyRoadMaterialTrackOffsets>[0], {
      road: true,
      designation: false,
      tunnel: false,
      oneway: false,
    });

    expect(paintValue(map, ROAD_TILE_LAYER_ID, "line-offset")).toBe(0);
  });

  it("ON中のレイヤーだけを中心対称に割り付け、OFF中のレイヤーはoffsetを0へ戻す", () => {
    const map = fakeMap();
    for (const id of ROAD_MATERIAL_TRACK_LAYER_IDS) map.addLayer({ id });

    applyRoadMaterialTrackOffsets(map as unknown as Parameters<typeof applyRoadMaterialTrackOffsets>[0], {
      road: true,
      designation: true,
      tunnel: false,
      oneway: false,
    });

    // ON中2件（road, designation）が中心対称（center=0.5）に割り付けられる。
    const center = (2 - 1) / 2;
    expect(paintValue(map, ROAD_TILE_LAYER_ID, "line-offset")).toBe((0 - center) * MATERIAL_TRACK_OFFSET_STEP);
    expect(paintValue(map, DESIGNATION_LAYER_ID, "line-offset")).toBe((1 - center) * MATERIAL_TRACK_OFFSET_STEP);
    // OFF中の2件（tunnel, oneway）はonLayerIdsに含まれないため0へ戻る（次にONにした際、
    // 古いoffset値が一瞬残らないようにする設計、コード上部のコメント参照）。
    expect(paintValue(map, TUNNEL_LAYER_ID, "line-offset")).toBe(0);
    expect(paintValue(map, ONEWAY_LAYER_ID, "line-offset")).toBe(0);
  });

  it("ON3件は中心対称に等間隔で割り付けられる（元の並び順=ROAD_MATERIAL_TRACK_LAYER_IDSの順）", () => {
    const map = fakeMap();
    for (const id of ROAD_MATERIAL_TRACK_LAYER_IDS) map.addLayer({ id });

    applyRoadMaterialTrackOffsets(map as unknown as Parameters<typeof applyRoadMaterialTrackOffsets>[0], {
      road: true,
      designation: true,
      tunnel: true,
      oneway: false,
    });

    const center = (3 - 1) / 2;
    expect(paintValue(map, ROAD_TILE_LAYER_ID, "line-offset")).toBe((0 - center) * MATERIAL_TRACK_OFFSET_STEP);
    expect(paintValue(map, DESIGNATION_LAYER_ID, "line-offset")).toBe((1 - center) * MATERIAL_TRACK_OFFSET_STEP);
    expect(paintValue(map, TUNNEL_LAYER_ID, "line-offset")).toBe((2 - center) * MATERIAL_TRACK_OFFSET_STEP);
    expect(paintValue(map, ONEWAY_LAYER_ID, "line-offset")).toBe(0);
  });

  it("地図にまだ追加されていないレイヤーはsetPaintPropertyを呼ばない", () => {
    const map = fakeMap();
    // ROAD_TILE_LAYER_IDだけ追加、他3件は未追加のまま。

    map.addLayer({ id: ROAD_TILE_LAYER_ID });
    applyRoadMaterialTrackOffsets(map as unknown as Parameters<typeof applyRoadMaterialTrackOffsets>[0], {
      road: true,
      designation: true,
      tunnel: true,
      oneway: true,
    });

    expect(map.paintCalls.map((c) => c.layerId)).toEqual([ROAD_TILE_LAYER_ID]);
  });
});

describe("applySecondaryAxisCasingStyles（二次軸の下敷き表現、改善計画T490）", () => {
  const axisOverlayLayers = [
    { key: "car_stress", layerId: "region-axis-car_stress-line", ensure: () => {} },
    { key: "stop_density", layerId: "region-axis-stop_density-line", ensure: () => {} },
  ];

  it("材料が同時表示中の軸だけ太く半透明の下敷きスタイルになる", () => {
    const map = fakeMap();
    map.addLayer({ id: "region-axis-car_stress-line" });
    map.addLayer({ id: "region-axis-stop_density-line" });

    applySecondaryAxisCasingStyles(
      map as unknown as Parameters<typeof applySecondaryAxisCasingStyles>[0],
      new Set(["car_stress"]),
      axisOverlayLayers
    );

    expect(paintValue(map, "region-axis-car_stress-line", "line-width")).toBe(SECONDARY_AXIS_CASING_WIDTH);
    expect(paintValue(map, "region-axis-car_stress-line", "line-opacity")).toBe(SECONDARY_AXIS_CASING_OPACITY);
    // 材料が表示されていないstop_densityは通常の太さ・不透明度のまま。
    expect(paintValue(map, "region-axis-stop_density-line", "line-width")).toBe(DEFAULT_ROAD_LINE_WIDTH);
    expect(paintValue(map, "region-axis-stop_density-line", "line-opacity")).toBe(KNOWN_LINE_OPACITY);
  });

  it("地図に追加されていない軸レイヤーはスキップする", () => {
    const map = fakeMap();
    // car_stressのみ追加、stop_densityは未追加。

    map.addLayer({ id: "region-axis-car_stress-line" });
    applySecondaryAxisCasingStyles(
      map as unknown as Parameters<typeof applySecondaryAxisCasingStyles>[0],
      new Set(["car_stress", "stop_density"]),
      axisOverlayLayers
    );

    expect(map.paintCalls.map((c) => c.layerId)).toEqual([
      "region-axis-car_stress-line",
      "region-axis-car_stress-line",
    ]);
  });
});

describe("clearRoadTileFeatureState（改善計画T490）", () => {
  it("road_surfaceソースが存在すればremoveFeatureStateをsource/sourceLayer単位で呼ぶ", () => {
    const map = fakeMap();
    map.addSource(ROAD_TILE_SOURCE_ID);

    clearRoadTileFeatureState(map as unknown as Parameters<typeof clearRoadTileFeatureState>[0]);

    expect(map.removeFeatureStateCalls).toEqual([
      { target: { source: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER } },
    ]);
  });

  it("road_surfaceソースが存在しなければ何もしない", () => {
    const map = fakeMap();

    clearRoadTileFeatureState(map as unknown as Parameters<typeof clearRoadTileFeatureState>[0]);

    expect(map.removeFeatureStateCalls).toEqual([]);
  });
});

describe("shouldClearDedicatedWayValueFeatureState（風・勾配が両方OFFになったかの判定、改善計画T490）", () => {
  it("両方OFFのときだけtrue", () => {
    expect(shouldClearDedicatedWayValueFeatureState(false, false)).toBe(true);
  });

  it("片方だけONならfalse（まだONの軸を巻き添えにしない）", () => {
    expect(shouldClearDedicatedWayValueFeatureState(true, false)).toBe(false);
    expect(shouldClearDedicatedWayValueFeatureState(false, true)).toBe(false);
  });

  it("両方ONならfalse", () => {
    expect(shouldClearDedicatedWayValueFeatureState(true, true)).toBe(false);
  });
});

describe("applyAxisFeatureStateValues（改善計画T490）", () => {
  it("road_surfaceソースが存在すれば全way_idぶんsetFeatureStateを呼ぶ", () => {
    const map = fakeMap();
    map.addSource(ROAD_TILE_SOURCE_ID);
    const values = new Map([
      [123, 5],
      [456, -2],
    ]);

    applyAxisFeatureStateValues(
      map as unknown as Parameters<typeof applyAxisFeatureStateValues>[0],
      "windPenalty",
      values
    );

    expect(map.setFeatureStateCalls).toEqual([
      { target: { source: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER, id: 123 }, state: { windPenalty: 5 } },
      { target: { source: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER, id: 456 }, state: { windPenalty: -2 } },
    ]);
  });

  it("road_surfaceソースが存在しなければ何もしない", () => {
    const map = fakeMap();

    applyAxisFeatureStateValues(
      map as unknown as Parameters<typeof applyAxisFeatureStateValues>[0],
      "windPenalty",
      new Map([[123, 5]])
    );

    expect(map.setFeatureStateCalls).toEqual([]);
  });
});

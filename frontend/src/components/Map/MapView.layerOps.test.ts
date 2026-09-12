// 改善計画T490: MapView.tsxのカバレッジ監査（2026-08-31）で発見された、docs/modules/
// frontend/static-map-layers.md・map-axis-coloring.mdが「暗黙の前提」として明記する
// 重要ロジックのうち、exportされておらずテスト対象から漏れていた関数群の単体テスト。
// MapView.overlayFilters.test.tsと同じ「実際のMapLibre Mapが必要とするメソッドだけを
// 持つフェイク」パターンを使う。
import { describe, expect, it } from "vitest";
import { DEDICATED_WAY_VALUE_AXES, axisLineLayerId, axisMapLayerId, type RampAxis } from "@/components/Map/axisLayers";
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
  buildAxisOverlayLayers,
  buildStaticOverlayLayers,
  clearRoadTileFeatureState,
  ensureDynamicWeatherLayer,
  shouldClearDedicatedWayValueFeatureState,
  ensureLayerFromSpec,
  dynamicWeatherIds,
} from "./MapView";

// __rcStyleReady=trueでrunWhenStyleReadyの即時実行分岐を通す
// （MapView.overlayFilters.test.ts/MapView.dataStatus.test.tsと同じ発想）。
function fakeMap() {
  const layers = new Set<string>();
  const sources = new Set<string>();
  const paintCalls: { layerId: string; name: string; value: unknown }[] = [];
  const layoutCalls: { layerId: string; name: string; value: unknown }[] = [];
  const filterCalls: { layerId: string; filter: unknown }[] = [];
  const images = new Set<string>();
  const setFeatureStateCalls: { target: unknown; state: unknown }[] = [];
  const removeFeatureStateCalls: { target: unknown }[] = [];
  const addedSpecs: { id: string; paint?: Record<string, unknown> }[] = [];
  return {
    __rcStyleReady: true,
    layers,
    sources,
    addedSpecs,
    paintCalls,
    layoutCalls,
    filterCalls,
    setFeatureStateCalls,
    removeFeatureStateCalls,
    getLayer: (id: string) => (layers.has(id) ? {} : undefined),
    addLayer: (spec: { id: string; paint?: Record<string, unknown> }) => {
      addedSpecs.push(spec);
      layers.add(spec.id);
    },
    getSource: (id: string) => (sources.has(id) ? {} : undefined),
    addSource: (id: string) => sources.add(id),
    setPaintProperty: (layerId: string, name: string, value: unknown) => paintCalls.push({ layerId, name, value }),
    setLayoutProperty: (layerId: string, name: string, value: unknown) => layoutCalls.push({ layerId, name, value }),
    setFilter: (layerId: string, filter: unknown) => filterCalls.push({ layerId, filter }),
    hasImage: (id: string) => images.has(id),
    addImage: (id: string) => images.add(id),
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

function rampAxisStub(axisId: string): RampAxis {
  return {
    axisId,
    label: axisId,
    category: "trafficSafety",
    tileInputs: [{ property: `${axisId}_per_km`, weight: 1 }],
    thresholds: [1, 2, 3],
    unit: "件/km",
    note: "",
  };
}

describe("二次軸rampレイヤーの下敷き表現（buildAxisOverlayLayers）", () => {
  const CAR_STRESS = axisMapLayerId("car_stress");
  const STOP_DENSITY = axisMapLayerId("stop_density");
  const rampAxes = [rampAxisStub("car_stress"), rampAxisStub("stop_density")];

  function addedPaint(map: ReturnType<typeof fakeMap>, layerId: string, name: string): unknown {
    return map.addedSpecs.find((spec) => spec.id === layerId)?.paint?.[name];
  }

  it("材料が同時表示中の軸だけ太く半透明の下敷きスタイルになる", () => {
    const map = fakeMap();

    for (const layer of buildAxisOverlayLayers(rampAxes, new Set([CAR_STRESS]))) {
      layer.ensure(map as unknown as Parameters<typeof layer.ensure>[0]);
    }

    expect(addedPaint(map, axisLineLayerId("car_stress"), "line-width")).toBe(SECONDARY_AXIS_CASING_WIDTH);
    expect(addedPaint(map, axisLineLayerId("car_stress"), "line-opacity")).toBe(SECONDARY_AXIS_CASING_OPACITY);
    // 材料が表示されていないstop_densityは通常の太さ・不透明度のまま。
    expect(addedPaint(map, axisLineLayerId("stop_density"), "line-width")).toBe(DEFAULT_ROAD_LINE_WIDTH);
    expect(addedPaint(map, axisLineLayerId("stop_density"), "line-opacity")).toBe(KNOWN_LINE_OPACITY);
  });

  // 下敷きの太さ・不透明度をspecの外から別途setPaintPropertyする形にすると、以後どこかで
  // ensure()が呼ばれた時点（絞り込みの再適用はレイヤーごとにensureを呼ぶ）にspec側の値へ
  // 無条件で巻き戻り、材料が1つも表示されていない軸まで太く半透明のまま描かれる。
  it("レイヤー追加後にensureが再度呼ばれても下敷きの有無が巻き戻らない", () => {
    const map = fakeMap();
    const layers = buildAxisOverlayLayers(rampAxes, new Set<string>());
    for (const layer of layers) layer.ensure(map as unknown as Parameters<typeof layers[0]["ensure"]>[0]);

    // 2回目以降はensureLayerFromSpecがsetPaintPropertyでspecを再適用する経路を通る。
    for (const layer of layers) layer.ensure(map as unknown as Parameters<typeof layers[0]["ensure"]>[0]);

    for (const axisId of ["car_stress", "stop_density"]) {
      expect(paintValue(map, axisLineLayerId(axisId), "line-width")).toBe(DEFAULT_ROAD_LINE_WIDTH);
      expect(paintValue(map, axisLineLayerId(axisId), "line-opacity")).toBe(KNOWN_LINE_OPACITY);
    }
  });

  it("材料が表示中の軸はensureを繰り返しても下敷きのまま", () => {
    const map = fakeMap();
    const layers = buildAxisOverlayLayers(rampAxes, new Set([CAR_STRESS, STOP_DENSITY]));
    for (const layer of layers) layer.ensure(map as unknown as Parameters<typeof layers[0]["ensure"]>[0]);
    for (const layer of layers) layer.ensure(map as unknown as Parameters<typeof layers[0]["ensure"]>[0]);

    expect(paintValue(map, axisLineLayerId("car_stress"), "line-width")).toBe(SECONDARY_AXIS_CASING_WIDTH);
    expect(paintValue(map, axisLineLayerId("stop_density"), "line-opacity")).toBe(SECONDARY_AXIS_CASING_OPACITY);
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

describe("shouldClearDedicatedWayValueFeatureState（専用way値配信軸が1つも表示されていないかの判定、改善計画T490）", () => {
  it("全軸OFFのときだけtrue", () => {
    expect(shouldClearDedicatedWayValueFeatureState({ windAxis: false, gradientAxis: false })).toBe(true);
    expect(shouldClearDedicatedWayValueFeatureState({})).toBe(true);
  });

  it("1つでもONならfalse（まだONの軸を巻き添えにしない）", () => {
    expect(shouldClearDedicatedWayValueFeatureState({ windAxis: true, gradientAxis: false })).toBe(false);
    expect(shouldClearDedicatedWayValueFeatureState({ windAxis: false, gradientAxis: true })).toBe(false);
    expect(shouldClearDedicatedWayValueFeatureState({ windAxis: true, gradientAxis: true })).toBe(false);
  });

  // 3件目の軸が公開されても、既存2軸をOFFにした瞬間に3件目の色分けが巻き添えで消えない。
  it("3件目の軸だけONでもfalse", () => {
    expect(
      shouldClearDedicatedWayValueFeatureState({ windAxis: false, gradientAxis: false, surface_tempAxis: true })
    ).toBe(false);
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

describe("buildStaticOverlayLayers（windAxis/gradientAxis/gradientFillのensureが既存レイヤーの色式を再適用する、T587）", () => {
  it("windAxisレイヤーが既に存在する場合、dedicatedWayValueDisplaysの変更をline-colorへ再適用する", () => {
    const map = fakeMap();
    const windEntry = buildStaticOverlayLayers([], DEDICATED_WAY_VALUE_AXES, undefined).find((l) => l.key === "windAxis")!;
    // 1回目: axisCatalogのフェッチ未完了を想定（boundaries未設定）でレイヤーを新規作成する。
    windEntry.ensure(map as unknown as Parameters<typeof windEntry.ensure>[0]);
    expect(map.layers.has(windEntry.layerId)).toBe(true);
    expect(map.paintCalls.filter((c) => c.layerId === windEntry.layerId)).toEqual([]);

    // 2回目: フェッチ完了後の正しいboundariesでensureを再実行する（実際にはstaticOverlayLayers
    // のuseMemo再計算→effect再実行で起きる）。既存レイヤーがあってもsetPaintPropertyで
    // line-colorが更新されなければならない。
    const windEntryAfter = buildStaticOverlayLayers(
      [],
      DEDICATED_WAY_VALUE_AXES,
      new Map([["wind", { kind: "difficulty" as const, unit: "", boundaries: [10, 20, 30, 40, 50] }]])
    ).find((l) => l.key === "windAxis")!;
    windEntryAfter.ensure(map as unknown as Parameters<typeof windEntryAfter.ensure>[0]);

    const paintCalls = map.paintCalls.filter((c) => c.layerId === windEntry.layerId && c.name === "line-color");
    expect(paintCalls).toHaveLength(1);
  });

  it("gradientAxis/gradientFillレイヤーが既に存在する場合も、boundariesの変更を再適用する", () => {
    const map = fakeMap();
    const before = buildStaticOverlayLayers([], DEDICATED_WAY_VALUE_AXES, undefined);
    const gradientAxisEntry = before.find((l) => l.key === "gradientAxis")!;
    const gradientFillEntry = before.find((l) => l.key === "gradientFill")!;
    gradientAxisEntry.ensure(map as unknown as Parameters<typeof gradientAxisEntry.ensure>[0]);
    gradientFillEntry.ensure(map as unknown as Parameters<typeof gradientFillEntry.ensure>[0]);
    expect(map.layers.has(gradientAxisEntry.layerId)).toBe(true);
    expect(map.layers.has(gradientFillEntry.layerId)).toBe(true);

    const after = buildStaticOverlayLayers(
      [],
      DEDICATED_WAY_VALUE_AXES,
      new Map([["gradient", { kind: "signed_material" as const, unit: "%", boundaries: [-10, -5, 0, 5, 10] }]])
    );
    const gradientAxisEntryAfter = after.find((l) => l.key === "gradientAxis")!;
    const gradientFillEntryAfter = after.find((l) => l.key === "gradientFill")!;
    gradientAxisEntryAfter.ensure(map as unknown as Parameters<typeof gradientAxisEntryAfter.ensure>[0]);
    gradientFillEntryAfter.ensure(map as unknown as Parameters<typeof gradientFillEntryAfter.ensure>[0]);

    expect(map.paintCalls.filter((c) => c.layerId === gradientAxisEntry.layerId && c.name === "line-color")).toHaveLength(1);
    expect(map.paintCalls.filter((c) => c.layerId === gradientFillEntry.layerId && c.name === "fill-color")).toHaveLength(1);
  });

  it("dedicatedWayValueLoadingの変更（フェッチ開始/完了）もwindAxis/gradientAxis/gradientFillのline-color/fill-colorへ再適用する（改善計画T607）", () => {
    const map = fakeMap();
    const before = buildStaticOverlayLayers([], DEDICATED_WAY_VALUE_AXES, undefined, new Map([["wind", false], ["gradient", false]]));
    const windEntry = before.find((l) => l.key === "windAxis")!;
    const gradientAxisEntry = before.find((l) => l.key === "gradientAxis")!;
    const gradientFillEntry = before.find((l) => l.key === "gradientFill")!;
    windEntry.ensure(map as unknown as Parameters<typeof windEntry.ensure>[0]);
    gradientAxisEntry.ensure(map as unknown as Parameters<typeof gradientAxisEntry.ensure>[0]);
    gradientFillEntry.ensure(map as unknown as Parameters<typeof gradientFillEntry.ensure>[0]);

    const after = buildStaticOverlayLayers([], DEDICATED_WAY_VALUE_AXES, undefined, new Map([["wind", true], ["gradient", true]]));
    const windEntryAfter = after.find((l) => l.key === "windAxis")!;
    const gradientAxisEntryAfter = after.find((l) => l.key === "gradientAxis")!;
    const gradientFillEntryAfter = after.find((l) => l.key === "gradientFill")!;
    windEntryAfter.ensure(map as unknown as Parameters<typeof windEntryAfter.ensure>[0]);
    gradientAxisEntryAfter.ensure(map as unknown as Parameters<typeof gradientAxisEntryAfter.ensure>[0]);
    gradientFillEntryAfter.ensure(map as unknown as Parameters<typeof gradientFillEntryAfter.ensure>[0]);

    expect(map.paintCalls.filter((c) => c.layerId === windEntry.layerId && c.name === "line-color")).toHaveLength(1);
    expect(map.paintCalls.filter((c) => c.layerId === gradientAxisEntry.layerId && c.name === "line-color")).toHaveLength(1);
    expect(map.paintCalls.filter((c) => c.layerId === gradientFillEntry.layerId && c.name === "fill-color")).toHaveLength(1);
  });
});

describe("ensureDynamicWeatherLayer（既存レイヤーへspecの変更を再適用する）", () => {
  // ソース名は`DYNAMIC_WEATHER_RENDERERS`の実際のキー（windVectorなら"arrow"）を使う。
  // 撤去済みの名前を`as any`で作ると、レイヤーidが実在しないものになり、実装が本当に
  // 対象のレイヤーを更新しているかを確かめられない。
  const gridFillSpec = (color: string, opacity: number) => ({
    arrow: {
      gridFill: {
        valueProperty: "speed",
        colorExpression: ["literal", color] as never,
        opacity,
      },
    },
  });

  it("gridFillレイヤーが既に存在する場合、colorExpression/opacityの変更を再適用する", () => {
    const map = fakeMap();
    const { layerId } = dynamicWeatherIds("windVector", "arrow", "fill");

    ensureDynamicWeatherLayer(map as never, "windVector", gridFillSpec("a", 0.4) as never);
    ensureDynamicWeatherLayer(map as never, "windVector", gridFillSpec("b", 0.6) as never);

    expect(map.layers.has(layerId)).toBe(true);
    expect(paintValue(map, layerId, "fill-color")).toEqual(["literal", "b"]);
    expect(paintValue(map, layerId, "fill-opacity")).toBe(0.6);
  });

  it("minValueToShow由来のfilterも再適用する（色だけ追随して間引き条件が古いままにならない）", () => {
    const map = fakeMap();
    const { layerId } = dynamicWeatherIds("windVector", "arrow", "fill");
    const withThreshold = (minValueToShow: number | undefined) => ({
      arrow: {
        gridFill: {
          valueProperty: "speed",
          colorExpression: ["literal", "a"] as never,
          opacity: 0.4,
          minValueToShow,
        },
      },
    });

    ensureDynamicWeatherLayer(map as never, "windVector", withThreshold(1) as never);
    ensureDynamicWeatherLayer(map as never, "windVector", withThreshold(5) as never);

    const lastFilter = [...map.filterCalls].reverse().find((c) => c.layerId === layerId);
    expect(lastFilter?.filter).toEqual([">", ["to-number", ["get", "speed"]], 5]);

    // しきい値が外れたらfilterも外れる（古い条件で間引き続けない）。
    ensureDynamicWeatherLayer(map as never, "windVector", withThreshold(undefined) as never);
    const clearedFilter = [...map.filterCalls].reverse().find((c) => c.layerId === layerId);
    expect(clearedFilter?.filter).toBeUndefined();
  });

  it("gridMarkのicon-size式もlayoutとして再適用する", () => {
    const map = fakeMap();
    const { layerId } = dynamicWeatherIds("windVector", "arrow", "mark");
    const mark = (maxScale: number) => ({
      arrow: {
        gridMark: {
          createIcon: () => ({ width: 1, height: 1, data: new Uint8ClampedArray(4) }),
          colorExpression: ["literal", "a"] as never,
          valueProperty: "speed",
          minScale: 0.5,
          maxScale,
          maxValueForFullScale: 15,
          haloColor: "#fff",
          haloWidth: 1,
        },
      },
    });

    ensureDynamicWeatherLayer(map as never, "windVector", mark(1.5) as never);
    ensureDynamicWeatherLayer(map as never, "windVector", mark(3) as never);

    const iconSize = [...map.layoutCalls].reverse().find((c) => c.layerId === layerId && c.name === "icon-size");
    expect(iconSize).toBeDefined();
    // visibilityは表示ON/OFFの状態そのものなので再適用しない。
    expect(map.layoutCalls.some((c) => c.name === "visibility")).toBe(false);
  });
});

describe("ensureLayerFromSpec（既存レイヤーへspecの全設定を再適用する）", () => {
  // T587は色式の再適用だけを直したため、filter・layoutが初回の値で固定される取り残しが
  // 残っていた。ensure系がspecを組み立ててこの1関数へ渡す形にすることで、
  // 「色は追随するのに間引き条件とサイズ曲線だけ古い」という片側の取り残しが起きない。
  const attributeEntry = () =>
    buildStaticOverlayLayers([], [], undefined).find((l) => l.key === "designation")!;

  it("既存レイヤーにはpaintだけでなくlayout・filterも再適用する", () => {
    const map = fakeMap();
    map.layers.add("test-layer");

    ensureLayerFromSpec(map as unknown as Parameters<typeof ensureLayerFromSpec>[0], {
      id: "test-layer",
      type: "symbol",
      source: "s",
      layout: { "icon-size": 2, visibility: "none" },
      paint: { "icon-opacity": 0.5 },
      filter: [">", ["get", "v"], 1] as never,
    }, { specOwnsFilter: true });

    expect(map.paintCalls).toEqual([{ layerId: "test-layer", name: "icon-opacity", value: 0.5 }]);
    // visibilityは表示ON/OFFの状態そのもの（specが持つのは追加時の初期値）なので上書きしない。
    expect(map.layoutCalls).toEqual([{ layerId: "test-layer", name: "icon-size", value: 2 }]);
    expect(map.filterCalls).toEqual([{ layerId: "test-layer", filter: [">", ["get", "v"], 1] }]);
  });

  it("持ち主のときは、specがfilterを持たなくなったら残っているfilterをundefinedで外す", () => {
    const map = fakeMap();
    map.layers.add("test-layer");

    ensureLayerFromSpec(map as unknown as Parameters<typeof ensureLayerFromSpec>[0], {
      id: "test-layer",
      type: "line",
      source: "s",
      paint: { "line-width": 1 },
    }, { specOwnsFilter: true });

    expect(map.filterCalls).toEqual([{ layerId: "test-layer", filter: undefined }]);
  });

  // 表示ON/OFFのたびに走るensureが、凡例のON/OFFから外側が与えた絞り込みを巻き戻して
  // いた（paintについて同じ構造をT712で直したが、filterに残っていた）。
  it("持ち主でないときは、外側が設定した絞り込みに一切触らない", () => {
    const map = fakeMap();
    map.layers.add("test-layer");

    ensureLayerFromSpec(map as unknown as Parameters<typeof ensureLayerFromSpec>[0], {
      id: "test-layer",
      type: "line",
      source: "s",
      paint: { "line-width": 1 },
    }, { specOwnsFilter: false });

    expect(map.filterCalls).toEqual([]);
    // paint・layoutの再適用（この関数の本来の役目）は止めない。
    expect(map.paintCalls).toEqual([{ layerId: "test-layer", name: "line-width", value: 1 }]);
  });

  it("filterを持てないraster等には触らない（MapLibreのstyle検証が弾くため）", () => {
    const map = fakeMap();
    map.layers.add("raster-layer");

    ensureLayerFromSpec(map as unknown as Parameters<typeof ensureLayerFromSpec>[0], {
      id: "raster-layer",
      type: "raster",
      source: "s",
      paint: { "raster-opacity": 0.4 },
    }, { specOwnsFilter: true });

    expect(map.filterCalls).toEqual([]);
  });

  it("レイヤーがまだ無ければaddLayerし、再適用は呼ばない", () => {
    const map = fakeMap();

    ensureLayerFromSpec(map as unknown as Parameters<typeof ensureLayerFromSpec>[0], {
      id: "new-layer",
      type: "line",
      source: "s",
      paint: { "line-width": 1 },
    }, { specOwnsFilter: true });

    expect(map.layers.has("new-layer")).toBe(true);
    expect(map.paintCalls).toEqual([]);
    expect(map.filterCalls).toEqual([]);
  });

  it("一次属性レイヤー（designation等）も再適用の対象になっている", () => {
    // T587の横展開漏れだった経路。ファクトリがensureLayerFromSpecを通るため、
    // 個別に再適用を書かなくても既存レイヤーへ色式・不透明度式が届く。
    const map = fakeMap();
    const entry = attributeEntry();
    entry.ensure(map as unknown as Parameters<typeof entry.ensure>[0]);
    expect(map.paintCalls).toEqual([]);

    entry.ensure(map as unknown as Parameters<typeof entry.ensure>[0]);

    const names = map.paintCalls.filter((c) => c.layerId === entry.layerId).map((c) => c.name);
    expect(names).toContain("line-color");
    expect(names).toContain("line-opacity");
  });
});

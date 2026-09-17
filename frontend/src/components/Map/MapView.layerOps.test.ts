// 改善計画T490: MapView.tsxのカバレッジ監査（2026-08-31）で発見された、docs/modules/
// frontend/static-map-layers.md・map-axis-coloring.mdが「暗黙の前提」として明記する
// 重要ロジックのうち、exportされておらずテスト対象から漏れていた関数群の単体テスト。
// MapView.overlayFilters.test.tsと同じ「実際のMapLibre Mapが必要とするメソッドだけを
// 持つフェイク」パターンを使う。
import { beforeEach, describe, expect, it } from "vitest";
import { setTileVersions } from "@/services/regionApi";
import { DEDICATED_WAY_VALUE_AXES, axisLineLayerId, axisMapLayerId, type RampAxis } from "@/components/Map/axisLayers";
import { KNOWN_LINE_OPACITY } from "@/components/Map/roadFilterAxes";
import {
  DEFAULT_ROAD_LINE_WIDTH,
  DESIGNATION_LAYER_ID,
  MATERIAL_TRACK_OFFSET_STEP,
  ONEWAY_LAYER_ID,
  ROAD_MATERIAL_TRACK_LAYER_IDS,
  ROAD_INSPECT_LAYER_ID,
  ROAD_TILE_LAYER_ID,
  ROAD_TILE_SOURCE_ID,
  ROAD_TILE_SOURCE_LAYER,
  SECONDARY_AXIS_CASING_OPACITY,
  SECONDARY_AXIS_CASING_WIDTH,
  TUNNEL_LAYER_ID,
  applyAxisFeatureStateValues,
  ensureRoadSurfaceTileLayer,
  applyInspectedWay,
  applyRoadMaterialTrackOffsets,
  buildAxisOverlayLayers,
  buildStaticOverlayLayers,
  clearRoadTileFeatureState,
  ensureDynamicWeatherLayer,
  shouldClearDedicatedWayValueFeatureState,
  ensureLayerFromSpec,
  dynamicWeatherIds,
  AREA_LAYER_OPACITY,
  WIND_COLOR_SCALE_EXPRESSION,
  PRECIPITATION_COLOR_SCALE_EXPRESSION,
} from "./MapView";
import { WIND_SPEED_COLOR_STOPS, WIND_SPEED_LEGEND_LEVELS } from "@/components/Map/windLayer";
import { PRECIPITATION_COLOR_STOPS, PRECIPITATION_INTENSITY_LEVELS } from "@/components/Map/precipitationNowcast";
import { DETAIL_CASING_LAYER_ID, DETAIL_LAYER_ID, drawDetailSegments } from "./MapView.routes";
import { legendBandKey } from "@/components/Map/mapColorLegend";
import { COLOR_HIDDEN } from "@/components/Map/valueScale";

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
  const addedSources: { id: string; spec: Record<string, unknown> }[] = [];
  return {
    __rcStyleReady: true,
    layers,
    sources,
    addedSpecs,
    addedSources,
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
    addSource: (id: string, spec?: Record<string, unknown>) => {
      addedSources.push({ id, spec: spec ?? {} });
      sources.add(id);
    },
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

// クリックして詳細を見ている道の強調。詳細だけ出しても、どの線の話かが分からないと
// 場所を取り違える。対象はタイルへ焼き込み済みのosm_way_idで1本へ絞る。
// タイル世代はbackendから実行時に届く（regionApi.setTileVersions）。届く前はソースを
// 作らない仕様のため、ソース生成を見るテストでは先に渡しておく。
beforeEach(() => {
  setTileVersions({ road_surface: "1-test", poi: "1-test", accident: "1-test" });
});

describe("applyInspectedWay（詳細を見ている道の強調）", () => {
  it("対象のwayだけを描くフィルタにして表示する", () => {
    const map = fakeMap();
    map.addLayer({ id: ROAD_INSPECT_LAYER_ID });

    applyInspectedWay(map as unknown as Parameters<typeof applyInspectedWay>[0], 156167860);

    expect(map.layoutCalls).toContainEqual({
      layerId: ROAD_INSPECT_LAYER_ID,
      name: "visibility",
      value: "visible",
    });
    expect(map.filterCalls.at(-1)).toEqual({
      layerId: ROAD_INSPECT_LAYER_ID,
      filter: ["==", ["get", "osm_way_id"], 156167860],
    });
  });

  it("nullで強調を消す（どのwayにも一致しないフィルタへ戻し、非表示にする）", () => {
    const map = fakeMap();
    map.addLayer({ id: ROAD_INSPECT_LAYER_ID });

    applyInspectedWay(map as unknown as Parameters<typeof applyInspectedWay>[0], null);

    expect(map.layoutCalls).toContainEqual({ layerId: ROAD_INSPECT_LAYER_ID, name: "visibility", value: "none" });
    expect(map.filterCalls.at(-1)?.filter).toEqual(["==", ["get", "osm_way_id"], -1]);
  });

  it("レイヤーがまだ無ければ何もしない（作り直しの途中でも落ちない）", () => {
    const map = fakeMap();

    applyInspectedWay(map as unknown as Parameters<typeof applyInspectedWay>[0], 1);

    expect(map.filterCalls).toHaveLength(0);
  });
});

describe("applyRoadMaterialTrackOffsets（並列トラック分離、改善計画T490）", () => {
  it("ONが1件だけならoffsetは0（並列に分ける相手がいない）", () => {
    const map = fakeMap();
    for (const id of ROAD_MATERIAL_TRACK_LAYER_IDS) map.addLayer({ id });

    applyRoadMaterialTrackOffsets(map as unknown as Parameters<typeof applyRoadMaterialTrackOffsets>[0], {
      roadSurface: true,
      roadType: false,
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
      roadSurface: true,
      roadType: false,
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
      roadSurface: true,
      roadType: false,
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
      roadSurface: true,
      roadType: false,
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

  // map.setStyle()の後の作り直しは各レイヤーのensureを順に呼ぶだけで、路面ソースを作る処理が
  // これより後に来ることがある。順序に頼っていた間は、ramp軸だけが
  // 「source "region-road-surface-tiles" not found」で落ち、その軸の色分けが戻らなかった。
  it("ソースがまだ無くても、ramp軸のensureが自分で路面ソースを用意してから追加する", () => {
    const map = fakeMap();
    expect(map.sources.has(ROAD_TILE_SOURCE_ID)).toBe(false);

    for (const layer of buildAxisOverlayLayers(rampAxes, new Set())) {
      layer.ensure(map as unknown as Parameters<typeof layer.ensure>[0]);
    }

    expect(map.sources.has(ROAD_TILE_SOURCE_ID)).toBe(true);
    for (const axis of rampAxes) expect(map.layers.has(axisLineLayerId(axis.axisId))).toBe(true);
  });

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
    for (const layer of layers) layer.ensure(map as unknown as Parameters<(typeof layers)[0]["ensure"]>[0]);

    // 2回目以降はensureLayerFromSpecがsetPaintPropertyでspecを再適用する経路を通る。
    for (const layer of layers) layer.ensure(map as unknown as Parameters<(typeof layers)[0]["ensure"]>[0]);

    for (const axisId of ["car_stress", "stop_density"]) {
      expect(paintValue(map, axisLineLayerId(axisId), "line-width")).toBe(DEFAULT_ROAD_LINE_WIDTH);
      expect(paintValue(map, axisLineLayerId(axisId), "line-opacity")).toBe(KNOWN_LINE_OPACITY);
    }
  });

  it("材料が表示中の軸はensureを繰り返しても下敷きのまま", () => {
    const map = fakeMap();
    const layers = buildAxisOverlayLayers(rampAxes, new Set([CAR_STRESS, STOP_DENSITY]));
    for (const layer of layers) layer.ensure(map as unknown as Parameters<(typeof layers)[0]["ensure"]>[0]);
    for (const layer of layers) layer.ensure(map as unknown as Parameters<(typeof layers)[0]["ensure"]>[0]);

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
      shouldClearDedicatedWayValueFeatureState({ windAxis: false, gradientAxis: false, surface_tempAxis: true }),
    ).toBe(false);
  });
});

describe("ensureRoadSurfaceTileLayer（路面タイルのsource）", () => {
  it("feature_keyをfeature.idへ昇格させる", () => {
    // 動的値配信（風・勾配）の鍵はタイルの`feature_key`列から作られる。ここが別の列
    // （`osm_way_id`等）だと、setFeatureStateのidがどの地物とも一致せず**エラーも警告も
    // 出ないまま色が一切付かない**。`feature_key`はズームによってway_idにもedge_idにも
    // なるため、way固有の列で代用できない。
    const map = fakeMap();

    ensureRoadSurfaceTileLayer(map as unknown as Parameters<typeof ensureRoadSurfaceTileLayer>[0]);

    const source = map.addedSources.find((s) => s.id === ROAD_TILE_SOURCE_ID);
    expect(source?.spec.promoteId).toEqual({ [ROAD_TILE_SOURCE_LAYER]: "feature_key" });
  });
});

describe("applyAxisFeatureStateValues（改善計画T490）", () => {
  it("road_surfaceソースが存在すれば全フィーチャーぶんsetFeatureStateを呼ぶ", () => {
    const map = fakeMap();
    map.addSource(ROAD_TILE_SOURCE_ID);
    // 鍵は路面タイルの`feature_key`そのもの。ズームによってway_idにもedge_idにもなるため、
    // 数値化せず受け取った文字列のままidへ渡す。
    const values = new Map([
      ["123", 5],
      ["w456-7", -2],
    ]);

    applyAxisFeatureStateValues(
      map as unknown as Parameters<typeof applyAxisFeatureStateValues>[0],
      "windPenalty",
      values,
    );

    expect(map.setFeatureStateCalls).toEqual([
      {
        target: { source: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER, id: "123" },
        state: { windPenalty: 5 },
      },
      {
        target: { source: ROAD_TILE_SOURCE_ID, sourceLayer: ROAD_TILE_SOURCE_LAYER, id: "w456-7" },
        state: { windPenalty: -2 },
      },
    ]);
  });

  it("road_surfaceソースが存在しなければ何もしない", () => {
    const map = fakeMap();

    applyAxisFeatureStateValues(
      map as unknown as Parameters<typeof applyAxisFeatureStateValues>[0],
      "windPenalty",
      new Map([["123", 5]]),
    );

    expect(map.setFeatureStateCalls).toEqual([]);
  });
});

describe("buildStaticOverlayLayers（windAxis/gradientAxisのensureが既存レイヤーの色式を再適用する、T587）", () => {
  it("windAxisレイヤーが既に存在する場合、dedicatedWayValueDisplaysの変更をline-colorへ再適用する", () => {
    const map = fakeMap();
    const windEntry = buildStaticOverlayLayers([], DEDICATED_WAY_VALUE_AXES, undefined).find(
      (l) => l.key === "windAxis",
    )!;
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
      new Map([["wind", { kind: "difficulty" as const, unit: "", boundaries: [10, 20, 30, 40, 50] }]]),
    ).find((l) => l.key === "windAxis")!;
    windEntryAfter.ensure(map as unknown as Parameters<typeof windEntryAfter.ensure>[0]);

    const paintCalls = map.paintCalls.filter((c) => c.layerId === windEntry.layerId && c.name === "line-color");
    expect(paintCalls).toHaveLength(1);
  });

  it("凡例で非表示にした段階は、色式のその段階だけが透明になる（filterでは絞り込めないため）", () => {
    const display = new Map([["gradient", { kind: "signed_material" as const, unit: "%", boundaries: [-1, 1] }]]);
    const visible = buildStaticOverlayLayers([], DEDICATED_WAY_VALUE_AXES, display, undefined, undefined).find(
      (l) => l.key === "gradientAxis",
    )!;
    const hidden = buildStaticOverlayLayers(
      [],
      DEDICATED_WAY_VALUE_AXES,
      display,
      undefined,
      new Map([["gradient", [legendBandKey(1)]]]),
    ).find((l) => l.key === "gradientAxis")!;

    const map = fakeMap();
    visible.ensure(map as unknown as Parameters<typeof visible.ensure>[0]);
    const created = map.addedSpecs.find((spec) => spec.id === visible.layerId)!;
    expect(JSON.stringify(created.paint)).not.toContain(COLOR_HIDDEN);

    hidden.ensure(map as unknown as Parameters<typeof hidden.ensure>[0]);
    const repaint = map.paintCalls.filter((c) => c.layerId === visible.layerId && c.name === "line-color");
    expect(repaint).toHaveLength(1);
    expect(JSON.stringify(repaint[0].value)).toContain(COLOR_HIDDEN);
  });

  it("gradientAxisレイヤーが既に存在する場合も、boundariesの変更を再適用する", () => {
    const map = fakeMap();
    const before = buildStaticOverlayLayers([], DEDICATED_WAY_VALUE_AXES, undefined);
    const gradientAxisEntry = before.find((l) => l.key === "gradientAxis")!;
    gradientAxisEntry.ensure(map as unknown as Parameters<typeof gradientAxisEntry.ensure>[0]);
    expect(map.layers.has(gradientAxisEntry.layerId)).toBe(true);

    const after = buildStaticOverlayLayers(
      [],
      DEDICATED_WAY_VALUE_AXES,
      new Map([["gradient", { kind: "signed_material" as const, unit: "%", boundaries: [-10, -5, 0, 5, 10] }]]),
    );
    const gradientAxisEntryAfter = after.find((l) => l.key === "gradientAxis")!;
    gradientAxisEntryAfter.ensure(map as unknown as Parameters<typeof gradientAxisEntryAfter.ensure>[0]);

    expect(
      map.paintCalls.filter((c) => c.layerId === gradientAxisEntry.layerId && c.name === "line-color"),
    ).toHaveLength(1);
  });

  it("dedicatedWayValueLoadingの変更（フェッチ開始/完了）もwindAxis/gradientAxisのline-colorへ再適用する（改善計画T607）", () => {
    const map = fakeMap();
    const before = buildStaticOverlayLayers(
      [],
      DEDICATED_WAY_VALUE_AXES,
      undefined,
      new Map([
        ["wind", false],
        ["gradient", false],
      ]),
    );
    const windEntry = before.find((l) => l.key === "windAxis")!;
    const gradientAxisEntry = before.find((l) => l.key === "gradientAxis")!;
    windEntry.ensure(map as unknown as Parameters<typeof windEntry.ensure>[0]);
    gradientAxisEntry.ensure(map as unknown as Parameters<typeof gradientAxisEntry.ensure>[0]);

    const after = buildStaticOverlayLayers(
      [],
      DEDICATED_WAY_VALUE_AXES,
      undefined,
      new Map([
        ["wind", true],
        ["gradient", true],
      ]),
    );
    const windEntryAfter = after.find((l) => l.key === "windAxis")!;
    const gradientAxisEntryAfter = after.find((l) => l.key === "gradientAxis")!;
    windEntryAfter.ensure(map as unknown as Parameters<typeof windEntryAfter.ensure>[0]);
    gradientAxisEntryAfter.ensure(map as unknown as Parameters<typeof gradientAxisEntryAfter.ensure>[0]);

    expect(map.paintCalls.filter((c) => c.layerId === windEntry.layerId && c.name === "line-color")).toHaveLength(1);
    expect(
      map.paintCalls.filter((c) => c.layerId === gradientAxisEntry.layerId && c.name === "line-color"),
    ).toHaveLength(1);
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
  const attributeEntry = () => buildStaticOverlayLayers([], [], undefined).find((l) => l.key === "designation")!;

  it("既存レイヤーにはpaintだけでなくlayout・filterも再適用する", () => {
    const map = fakeMap();
    map.layers.add("test-layer");

    ensureLayerFromSpec(
      map as unknown as Parameters<typeof ensureLayerFromSpec>[0],
      {
        id: "test-layer",
        type: "symbol",
        source: "s",
        layout: { "icon-size": 2, visibility: "none" },
        paint: { "icon-opacity": 0.5 },
        filter: [">", ["get", "v"], 1] as never,
      },
      { specOwnsFilter: true },
    );

    expect(map.paintCalls).toEqual([{ layerId: "test-layer", name: "icon-opacity", value: 0.5 }]);
    // visibilityは表示ON/OFFの状態そのもの（specが持つのは追加時の初期値）なので上書きしない。
    expect(map.layoutCalls).toEqual([{ layerId: "test-layer", name: "icon-size", value: 2 }]);
    expect(map.filterCalls).toEqual([{ layerId: "test-layer", filter: [">", ["get", "v"], 1] }]);
  });

  it("持ち主のときは、specがfilterを持たなくなったら残っているfilterをundefinedで外す", () => {
    const map = fakeMap();
    map.layers.add("test-layer");

    ensureLayerFromSpec(
      map as unknown as Parameters<typeof ensureLayerFromSpec>[0],
      {
        id: "test-layer",
        type: "line",
        source: "s",
        paint: { "line-width": 1 },
      },
      { specOwnsFilter: true },
    );

    expect(map.filterCalls).toEqual([{ layerId: "test-layer", filter: undefined }]);
  });

  // 表示ON/OFFのたびに走るensureが、凡例のON/OFFから外側が与えた絞り込みを巻き戻して
  // いた（paintについて同じ構造をT712で直したが、filterに残っていた）。
  it("持ち主でないときは、外側が設定した絞り込みに一切触らない", () => {
    const map = fakeMap();
    map.layers.add("test-layer");

    ensureLayerFromSpec(
      map as unknown as Parameters<typeof ensureLayerFromSpec>[0],
      {
        id: "test-layer",
        type: "line",
        source: "s",
        paint: { "line-width": 1 },
      },
      { specOwnsFilter: false },
    );

    expect(map.filterCalls).toEqual([]);
    // paint・layoutの再適用（この関数の本来の役目）は止めない。
    expect(map.paintCalls).toEqual([{ layerId: "test-layer", name: "line-width", value: 1 }]);
  });

  it("filterを持てないraster等には触らない（MapLibreのstyle検証が弾くため）", () => {
    const map = fakeMap();
    map.layers.add("raster-layer");

    ensureLayerFromSpec(
      map as unknown as Parameters<typeof ensureLayerFromSpec>[0],
      {
        id: "raster-layer",
        type: "raster",
        source: "s",
        paint: { "raster-opacity": 0.4 },
      },
      { specOwnsFilter: true },
    );

    expect(map.filterCalls).toEqual([]);
  });

  it("レイヤーがまだ無ければaddLayerし、再適用は呼ばない", () => {
    const map = fakeMap();

    ensureLayerFromSpec(
      map as unknown as Parameters<typeof ensureLayerFromSpec>[0],
      {
        id: "new-layer",
        type: "line",
        source: "s",
        paint: { "line-width": 1 },
      },
      { specOwnsFilter: true },
    );

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

describe("区間色分け線の縁取り（T770）", () => {
  const MODE = {
    id: "difficulty",
    label: "総合難易度",
    colorExpression: ["literal", "#16a34a"] as unknown as maplibregl.ExpressionSpecification,
    legend: [],
  };

  function drawOnce() {
    const map = fakeMap();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    drawDetailSegments(map as any, [], MODE as any, []);
    return map;
  }

  it("縁取りは色分け線より先に追加される（＝下に描かれる）", () => {
    const map = drawOnce();
    const ids = map.addedSpecs.map((spec) => spec.id);

    expect(ids).toContain(DETAIL_CASING_LAYER_ID);
    expect(ids.indexOf(DETAIL_CASING_LAYER_ID)).toBeLessThan(ids.indexOf(DETAIL_LAYER_ID));
  });

  it("縁取りは色分け線より太く、線色に依存しない一定色で描く", () => {
    const map = drawOnce();
    const casing = map.addedSpecs.find((spec) => spec.id === DETAIL_CASING_LAYER_ID);
    const line = map.addedSpecs.find((spec) => spec.id === DETAIL_LAYER_ID);

    expect(Number(casing?.paint?.["line-width"])).toBeGreaterThan(Number(line?.paint?.["line-width"]));
    expect(typeof casing?.paint?.["line-color"]).toBe("string");
  });

  it("凡例で非表示にしたカテゴリの縁だけが残らないよう、同じfilterを適用する", () => {
    const map = drawOnce();
    const casingFilter = map.filterCalls.find((c) => c.layerId === DETAIL_CASING_LAYER_ID);
    const lineFilter = map.filterCalls.find((c) => c.layerId === DETAIL_LAYER_ID);

    expect(casingFilter?.filter).toEqual(lineFilter?.filter);
  });
});

// 起伏（陰影）のレイヤー登録（T914）。hillshadeは不透明度のpaintプロパティを持たないため、
// 面レイヤー共通の濃さが影・光の色のalphaとして渡っていることを固定する——ここが素の色に
// 戻ると、平地は透明のままでも斜面だけが他の面レイヤーより濃くなる。
describe("ensureTerrainHillshadeLayer（起伏）", () => {
  it("raster-demソースとhillshadeレイヤーを作り、共通の濃さを影・光の色へ載せる", () => {
    const map = fakeMap();

    const entry = buildStaticOverlayLayers([], []).find((layer) => layer.key === "hillshade");
    entry?.ensure(map as unknown as Parameters<typeof ensureLayerFromSpec>[0]);

    const spec = map.addedSpecs.find((s) => s.id === entry?.layerId) as
      { id: string; type?: string; paint?: Record<string, unknown> } | undefined;
    expect(spec?.type).toBe("hillshade");
    expect(String(spec?.paint?.["hillshade-shadow-color"])).toContain(String(AREA_LAYER_OPACITY));
    expect(String(spec?.paint?.["hillshade-highlight-color"])).toContain(String(AREA_LAYER_OPACITY));
  });

  // 平坦な画素にも光を塗る計算方法（basic・multidirectional）は、面レイヤの「値のある所だけ
  // 塗る」を満たさない。既定のstandardは傾きのsinに比例するため、関東平野の傾き（数度）では
  // 実効の不透明度が0.03を下回り、出ていても気づけない（T916）。
  it("平坦な所を塗らず、緩い斜面でも読める計算方法を指定する", () => {
    const map = fakeMap();

    const entry = buildStaticOverlayLayers([], []).find((layer) => layer.key === "hillshade");
    entry?.ensure(map as unknown as Parameters<typeof ensureLayerFromSpec>[0]);

    const spec = map.addedSpecs.find((s) => s.id === entry?.layerId);
    expect(spec?.paint?.["hillshade-method"]).toBe("igor");
    expect(spec?.paint?.["hillshade-exaggeration"]).toBe(1);
  });

  // 標高の読み方だけを強調する（タイルの値は実際の標高のまま）。倍率が1へ戻ると、
  // 緩い斜面が再び見えなくなる。
  it("標高を垂直方向へ強調して読むcustom encodingのソースを作る", () => {
    const map = fakeMap();

    const entry = buildStaticOverlayLayers([], []).find((layer) => layer.key === "hillshade");
    entry?.ensure(map as unknown as Parameters<typeof ensureLayerFromSpec>[0]);

    const source = map.addedSources.find((added) => added.spec.type === "raster-dem")?.spec as
      { encoding?: string; blueFactor?: number; baseShift?: number } | undefined;
    expect(source?.encoding).toBe("custom");
    // mapbox encodingの係数（blue=0.1・baseShift=10000）を同じ倍率で掛けたものになる。
    const exaggeration = (source?.blueFactor ?? 0) / 0.1;
    expect(exaggeration).toBeGreaterThan(1);
    expect(source?.baseShift).toBeCloseTo(10000 * exaggeration, 6);
  });
});

// 地図に出る色と凡例の行が一致すること（T915）。連続補間で塗っていたころは、帯の中ほどの
// 値（風4.0m/s・降水6mm/h等）がどの色見本とも違う色になっていた（実測で最大ΔE 32）。
describe("色の段（地図と凡例の一致）", () => {
  /** step式（["step", 値, 色0, 下限1, 色1, …]）を、指定した値で評価する。
   *
   * **先頭が"step"であることを先に確かめる。** interpolate式は要素が1つずれるだけで
   * 下限と色の対が同じ位置に並ぶため、種類を見ずに読むと連続補間のままでも同じ色を返し、
   * この検査が何も守らなくなる。 */
  function colorAt(expression: unknown, value: number): string {
    const parts = expression as unknown[];
    expect(parts[0]).toBe("step");
    const [, , first, ...rest] = parts as [string, unknown, string, ...unknown[]];
    let color = first;
    for (let i = 0; i < rest.length; i += 2) {
      if (value < (rest[i] as number)) break;
      color = rest[i + 1] as string;
    }
    return color;
  }

  it("風: 帯の中ほどの値が、その帯の凡例の色そのもので塗られる", () => {
    WIND_SPEED_COLOR_STOPS.forEach((stop, index) => {
      const next = WIND_SPEED_COLOR_STOPS[index + 1];
      const middle = next === undefined ? stop.speedMs + 5 : (stop.speedMs + next.speedMs) / 2;
      expect(colorAt(WIND_COLOR_SCALE_EXPRESSION, middle)).toBe(stop.color);
      // 凡例の先頭は「無風（矢印なし）」で帯を持たないため1つずらす。
      expect(WIND_SPEED_LEGEND_LEVELS[index + 1].color).toBe(stop.color);
    });
  });

  it("風: ユーザー報告の4.0m/sが「心地よい風」の帯の色になる", () => {
    expect(colorAt(WIND_COLOR_SCALE_EXPRESSION, 4.0)).toBe(WIND_SPEED_COLOR_STOPS[2].color);
  });

  it("降水: 帯の中ほどの値が、その帯の凡例の色そのもので塗られる", () => {
    PRECIPITATION_COLOR_STOPS.forEach((stop, index) => {
      const next = PRECIPITATION_COLOR_STOPS[index + 1];
      const middle = next === undefined ? stop.mmPerHour + 10 : (stop.mmPerHour + next.mmPerHour) / 2;
      expect(colorAt(PRECIPITATION_COLOR_SCALE_EXPRESSION, middle)).toBe(stop.color);
      expect(PRECIPITATION_INTENSITY_LEVELS[index].color).toBe(stop.color);
    });
  });
});

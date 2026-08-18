// このファイルはMapView.tsxのensure*Layer関数経由でregionApi.ts: accidentTileUrl()等の
// window.location参照コードを実行する（改善計画: environmentMatchGlobs修正）ため、他の
// Map/*.test.tsと違いjsdom環境が必要（既定のまま。node環境docblockを付けない）。
import { createExpression } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";
import { DEFAULT_SAFETY_RECIPE } from "@/components/Map/safetyExpression";
import {
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_TRAFFIC_STRESS_RECIPE,
} from "@/components/Map/trafficStressExpression";
import {
  BICYCLE_INFRA_LAYER_ID,
  SAFETY_LAYER_ID,
  STOP_POI_LAYER_ID,
  SUPPLY_POI_LAYER_ID,
  TRAFFIC_STRESS_LAYER_ID,
  setStaticOverlayFilters,
} from "./MapView";
import type { StaticFilterAxisId } from "./staticAttributeLayers";

// setStaticOverlayFilters（改善計画: 交通ストレスレシピ調整UIパネル）が読む最小限のmap
// フェイク。__rcStyleReady=trueでrunWhenStyleReadyの即時実行分岐を通す
// （MapView.dataStatus.test.tsのfakeMapと同じ発想）。
function fakeMap() {
  const layers = new Set<string>();
  const sources = new Set<string>();
  const setFilterCalls: { layerId: string; filter: unknown }[] = [];
  return {
    __rcStyleReady: true,
    getLayer: (id: string) => (layers.has(id) ? {} : undefined),
    addLayer: (spec: { id: string }) => layers.add(spec.id),
    getSource: (id: string) => (sources.has(id) ? {} : undefined),
    addSource: (id: string) => sources.add(id),
    setFilter: (layerId: string, filter: unknown) => setFilterCalls.push({ layerId, filter }),
    setPaintProperty: () => {},
    setFilterCalls,
  };
}

function evaluateFilter(filter: unknown, properties: Record<string, unknown>): boolean {
  const parsed = createExpression(filter);
  if (parsed.result !== "success") throw new Error("filter式の構築に失敗しました");
  return Boolean(parsed.value.evaluate({ zoom: 14 }, { type: "Unknown", properties }));
}

// hiddenKeysByAxisは全軸ぶんの完全なRecordを要求するが、テストでは触れる軸だけ指定できれば
// 十分（setStaticOverlayFilters内は`hiddenKeysByAxis[axis.axisId] ?? []`で未指定軸を
// 空配列扱いする）。
function hiddenKeys(partial: Partial<Record<StaticFilterAxisId, readonly string[]>>): Record<StaticFilterAxisId, readonly string[]> {
  return partial as Record<StaticFilterAxisId, readonly string[]>;
}

// 呼び出し側の引数を短くするための既定4引数目以降のショートハンド（改善計画: 車との近さ
// 材料の共有元化で6引数になったが、道路適正・自動車密度は個別に上書きしないテストが
// 大半のため既定値を使い回す）。
const DEFAULT_ROAD_SUITABILITY_AND_MOTOR_VEHICLE_DENSITY = [
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
] as const;

describe("setStaticOverlayFilters（交通ストレスレシピの追従）", () => {
  it("trafficStressレイヤーのフィルタは渡した道路適正レシピに追従する", () => {
    // base_by_highwayは道路適正レシピ側（改善計画: 車との近さ材料の共有元化）。
    const customRoadSuitabilityRecipe = {
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      base_by_highway: { ...DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway, secondary: 1 },
    };
    // 「レベル1を隠す」絞り込み中に、highway=secondaryがどちらの側に分類されるかで
    // レシピが実際に効いているかを検証する。
    const withHiddenLevel1 = hiddenKeys({ trafficStress: ["1"] });

    const mapDefault = fakeMap();
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      mapDefault as any,
      withHiddenLevel1,
      DEFAULT_TRAFFIC_STRESS_RECIPE,
      DEFAULT_SAFETY_RECIPE,
      ...DEFAULT_ROAD_SUITABILITY_AND_MOTOR_VEHICLE_DENSITY,
    );
    const defaultFilter = mapDefault.setFilterCalls.find((c) => c.layerId === TRAFFIC_STRESS_LAYER_ID)!.filter;

    const mapCustom = fakeMap();
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      mapCustom as any,
      withHiddenLevel1,
      DEFAULT_TRAFFIC_STRESS_RECIPE,
      DEFAULT_SAFETY_RECIPE,
      customRoadSuitabilityRecipe,
      DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    );
    const customFilter = mapCustom.setFilterCalls.find((c) => c.layerId === TRAFFIC_STRESS_LAYER_ID)!.filter;

    // 既定レシピ（secondary=3）で「レベル1を隠す」フィルタは、highway=secondaryを通す
    // （secondaryはレベル1ではないため）。customRecipe（secondary=1）では同じ
    // 「レベル1を隠す」フィルタが、highway=secondaryを弾く（secondaryがレベル1になったため）。
    expect(evaluateFilter(defaultFilter, { highway: "secondary" })).toBe(true);
    expect(evaluateFilter(customFilter, { highway: "secondary" })).toBe(false);
  });

  it("trafficStress以外の軸（bicycleInfra等）はレシピに影響されない", () => {
    const withHiddenProhibited = hiddenKeys({ bicycleInfra: ["prohibited"] });

    const mapDefault = fakeMap();
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      mapDefault as any,
      withHiddenProhibited,
      DEFAULT_TRAFFIC_STRESS_RECIPE,
      DEFAULT_SAFETY_RECIPE,
      ...DEFAULT_ROAD_SUITABILITY_AND_MOTOR_VEHICLE_DENSITY,
    );
    const defaultFilter = mapDefault.setFilterCalls.find((c) => c.layerId === BICYCLE_INFRA_LAYER_ID)!.filter;

    const customRecipe = { ...DEFAULT_TRAFFIC_STRESS_RECIPE, lanes_low_adjustment: -3 };
    const mapCustom = fakeMap();
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      mapCustom as any,
      withHiddenProhibited,
      customRecipe,
      DEFAULT_SAFETY_RECIPE,
      ...DEFAULT_ROAD_SUITABILITY_AND_MOTOR_VEHICLE_DENSITY,
    );
    const customFilter = mapCustom.setFilterCalls.find((c) => c.layerId === BICYCLE_INFRA_LAYER_ID)!.filter;

    expect(customFilter).toEqual(defaultFilter);
  });
});

// 安全度も交通ストレスと同じ理由でレシピに追従する（改善計画: 安全度レシピ）。
describe("setStaticOverlayFilters（安全度レシピの追従）", () => {
  it("safetyレイヤーのフィルタは渡した道路適正レシピに追従する", () => {
    const customRoadSuitabilityRecipe = {
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      base_by_highway: { ...DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway, secondary: 1 },
    };
    const withHiddenLevel1 = hiddenKeys({ safety: ["1"] });

    const mapDefault = fakeMap();
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      mapDefault as any,
      withHiddenLevel1,
      DEFAULT_TRAFFIC_STRESS_RECIPE,
      DEFAULT_SAFETY_RECIPE,
      ...DEFAULT_ROAD_SUITABILITY_AND_MOTOR_VEHICLE_DENSITY,
    );
    const defaultFilter = mapDefault.setFilterCalls.find((c) => c.layerId === SAFETY_LAYER_ID)!.filter;

    const mapCustom = fakeMap();
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      mapCustom as any,
      withHiddenLevel1,
      DEFAULT_TRAFFIC_STRESS_RECIPE,
      DEFAULT_SAFETY_RECIPE,
      customRoadSuitabilityRecipe,
      DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    );
    const customFilter = mapCustom.setFilterCalls.find((c) => c.layerId === SAFETY_LAYER_ID)!.filter;

    // 既定レシピ（secondary=3）で「レベル1を隠す」フィルタは、highway=secondaryを通す
    // （secondaryはレベル1ではないため）。customRecipe（secondary=1）では同じ
    // 「レベル1を隠す」フィルタが、highway=secondaryを弾く（secondaryがレベル1になったため）。
    expect(evaluateFilter(defaultFilter, { highway: "secondary" })).toBe(true);
    expect(evaluateFilter(customFilter, { highway: "secondary" })).toBe(false);
  });

  it("safety以外の軸（bicycleInfra等）は安全度レシピに影響されない", () => {
    const withHiddenProhibited = hiddenKeys({ bicycleInfra: ["prohibited"] });

    const mapDefault = fakeMap();
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      mapDefault as any,
      withHiddenProhibited,
      DEFAULT_TRAFFIC_STRESS_RECIPE,
      DEFAULT_SAFETY_RECIPE,
      ...DEFAULT_ROAD_SUITABILITY_AND_MOTOR_VEHICLE_DENSITY,
    );
    const defaultFilter = mapDefault.setFilterCalls.find((c) => c.layerId === BICYCLE_INFRA_LAYER_ID)!.filter;

    const customRecipe = { ...DEFAULT_SAFETY_RECIPE, lit_adjustment: -3 };
    const mapCustom = fakeMap();
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      mapCustom as any,
      withHiddenProhibited,
      DEFAULT_TRAFFIC_STRESS_RECIPE,
      customRecipe,
      ...DEFAULT_ROAD_SUITABILITY_AND_MOTOR_VEHICLE_DENSITY,
    );
    const customFilter = mapCustom.setFilterCalls.find((c) => c.layerId === BICYCLE_INFRA_LAYER_ID)!.filter;

    expect(customFilter).toEqual(defaultFilter);
  });
});

// 改善計画T101: 停止要因POI・補給休憩POIは同じベクタタイル（kindプロパティ）を共有するため、
// baseFilter（legendFilter.ts参照）でお互いのkind値を除外できているかを検証する。
// これが効いていないと、例えば「補給・休憩」レイヤーに信号・横断歩道の点が混ざって
// 表示されてしまう（stopPoiDefs/supplyPoiDefsのCOLOR_UNKNOWNフォールバック色で）。
describe("setStaticOverlayFilters（停止要因POI・補給休憩POIのkind分離、改善計画T101）", () => {
  it("stopPoiレイヤーのフィルタはstopPoi側のkindのみ通し、supplyPoi側のkindは弾く", () => {
    const map = fakeMap();
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map as any,
      hiddenKeys({}),
      DEFAULT_TRAFFIC_STRESS_RECIPE,
      DEFAULT_SAFETY_RECIPE,
      ...DEFAULT_ROAD_SUITABILITY_AND_MOTOR_VEHICLE_DENSITY,
    );
    const filter = map.setFilterCalls.find((c) => c.layerId === STOP_POI_LAYER_ID)!.filter;

    expect(evaluateFilter(filter, { kind: "traffic_signals" })).toBe(true);
    expect(evaluateFilter(filter, { kind: "convenience" })).toBe(false);
  });

  it("supplyPoiレイヤーのフィルタはsupplyPoi側のkindのみ通し、stopPoi側のkindは弾く", () => {
    const map = fakeMap();
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map as any,
      hiddenKeys({}),
      DEFAULT_TRAFFIC_STRESS_RECIPE,
      DEFAULT_SAFETY_RECIPE,
      ...DEFAULT_ROAD_SUITABILITY_AND_MOTOR_VEHICLE_DENSITY,
    );
    const filter = map.setFilterCalls.find((c) => c.layerId === SUPPLY_POI_LAYER_ID)!.filter;

    expect(evaluateFilter(filter, { kind: "convenience" })).toBe(true);
    expect(evaluateFilter(filter, { kind: "traffic_signals" })).toBe(false);
  });

  it("凡例の非表示操作中でも、相手方レイヤーのkindはbaseFilterにより引き続き除外される", () => {
    const map = fakeMap();
    // stopPoiの「信号を隠す」操作中でも、supplyPoiレイヤー自体はstopPoi側のkindを通さない。
    const withHiddenTrafficSignals = hiddenKeys({ stopPoi: ["traffic_signals"] });
    setStaticOverlayFilters(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map as any,
      withHiddenTrafficSignals,
      DEFAULT_TRAFFIC_STRESS_RECIPE,
      DEFAULT_SAFETY_RECIPE,
      ...DEFAULT_ROAD_SUITABILITY_AND_MOTOR_VEHICLE_DENSITY,
    );
    const supplyFilter = map.setFilterCalls.find((c) => c.layerId === SUPPLY_POI_LAYER_ID)!.filter;

    expect(evaluateFilter(supplyFilter, { kind: "traffic_signals" })).toBe(false);
    expect(evaluateFilter(supplyFilter, { kind: "convenience" })).toBe(true);
  });
});

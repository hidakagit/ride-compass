// このファイルはMapView.tsxのensure*Layer関数経由でregionApi.ts: accidentTileUrl()等の
// window.location参照コードを実行する（改善計画: environmentMatchGlobs修正）ため、他の
// Map/*.test.tsと違いjsdom環境が必要（既定のまま。node環境docblockを付けない）。
import { createExpression } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";
import { axisLineLayerId } from "@/components/Map/axisLayers";
import {
  BICYCLE_INFRA_LAYER_ID,
  STATIC_OVERLAY_LAYERS,
  STOP_POI_LAYER_ID,
  SUPPLY_POI_LAYER_ID,
  setStaticOverlayFilters,
} from "./MapView";
import { STATIC_FILTER_AXES, type StaticFilterAxisId } from "./staticAttributeLayers";

// setStaticOverlayFiltersが読む最小限のmapフェイク。__rcStyleReady=trueでrunWhenStyleReadyの
// 即時実行分岐を通す（MapView.dataStatus.test.tsのfakeMapと同じ発想）。
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

// 改善計画T292: 車ストレス（車の圧迫感）は専用Pythonレシピの廃止に伴い、他の推定軸
// （停止密度・事故密度等）と同じ汎用ramp機構（axis:car_stress、axisLineLayerId経由）へ
// 統合された。setStaticOverlayFiltersはレシピ引数を取らなくなり、車の圧迫感専用の
// フィルタ差し替えロジックも不要になった（STATIC_FILTER_AXESの静的なlegendをそのまま使う）。
describe("setStaticOverlayFilters（改善計画T292: 車の圧迫感を含むramp軸の汎用フィルタ適用）", () => {
  it("自転車インフラレイヤーのフィルタは指定した非表示キーを反映する", () => {
    const map = fakeMap();
    setStaticOverlayFilters(
      map as unknown as Parameters<typeof setStaticOverlayFilters>[0],
      hiddenKeys({ bicycleInfra: ["prohibited"] }),
      STATIC_OVERLAY_LAYERS,
      STATIC_FILTER_AXES
    );

    const filter = map.setFilterCalls.find((c) => c.layerId === BICYCLE_INFRA_LAYER_ID)!.filter;
    expect(evaluateFilter(filter, { bicycle_infra: "prohibited" })).toBe(false);
    expect(evaluateFilter(filter, { bicycle_infra: "separated" })).toBe(true);
  });

  it("車の圧迫感（axis:car_stress）のrampレイヤーにもフィルタが設定される", () => {
    const map = fakeMap();
    setStaticOverlayFilters(map as unknown as Parameters<typeof setStaticOverlayFilters>[0], hiddenKeys({}), STATIC_OVERLAY_LAYERS, STATIC_FILTER_AXES);

    const layerId = axisLineLayerId("car_stress");
    expect(map.setFilterCalls.some((c) => c.layerId === layerId)).toBe(true);
  });
});

// 改善計画T101: 停止要因POI・補給休憩POIは同じベクタタイル（kindプロパティ）を共有するため、
// baseFilter（legendFilter.ts参照）でお互いのkind値を除外できているかを検証する。
// これが効いていないと、例えば「補給・休憩」レイヤーに信号・横断歩道の点が混ざって
// 表示されてしまう（stopPoiDefs/supplyPoiDefsのCOLOR_UNKNOWNフォールバック色で）。
describe("setStaticOverlayFilters（停止要因POI・補給休憩POIのkind分離、改善計画T101）", () => {
  it("stopPoiレイヤーのフィルタはstopPoi側のkindのみ通し、supplyPoi側のkindは弾く", () => {
    const map = fakeMap();
    setStaticOverlayFilters(map as unknown as Parameters<typeof setStaticOverlayFilters>[0], hiddenKeys({}), STATIC_OVERLAY_LAYERS, STATIC_FILTER_AXES);
    const filter = map.setFilterCalls.find((c) => c.layerId === STOP_POI_LAYER_ID)!.filter;

    expect(evaluateFilter(filter, { kind: "traffic_signals" })).toBe(true);
    expect(evaluateFilter(filter, { kind: "convenience" })).toBe(false);
  });

  it("supplyPoiレイヤーのフィルタはsupplyPoi側のkindのみ通し、stopPoi側のkindは弾く", () => {
    const map = fakeMap();
    setStaticOverlayFilters(map as unknown as Parameters<typeof setStaticOverlayFilters>[0], hiddenKeys({}), STATIC_OVERLAY_LAYERS, STATIC_FILTER_AXES);
    const filter = map.setFilterCalls.find((c) => c.layerId === SUPPLY_POI_LAYER_ID)!.filter;

    expect(evaluateFilter(filter, { kind: "convenience" })).toBe(true);
    expect(evaluateFilter(filter, { kind: "traffic_signals" })).toBe(false);
  });

  it("凡例の非表示操作中でも、相手方レイヤーのkindはbaseFilterにより引き続き除外される", () => {
    const map = fakeMap();
    // stopPoiの「信号を隠す」操作中でも、supplyPoiレイヤー自体はstopPoi側のkindを通さない。
    const withHiddenTrafficSignals = hiddenKeys({ stopPoi: ["traffic_signals"] });
    setStaticOverlayFilters(map as unknown as Parameters<typeof setStaticOverlayFilters>[0], withHiddenTrafficSignals, STATIC_OVERLAY_LAYERS, STATIC_FILTER_AXES);
    const supplyFilter = map.setFilterCalls.find((c) => c.layerId === SUPPLY_POI_LAYER_ID)!.filter;

    expect(evaluateFilter(supplyFilter, { kind: "traffic_signals" })).toBe(false);
    expect(evaluateFilter(supplyFilter, { kind: "convenience" })).toBe(true);
  });
});

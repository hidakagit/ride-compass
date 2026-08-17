import { createExpression } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";
import { DEFAULT_SAFETY_RECIPE } from "@/components/Map/safetyExpression";
import { DEFAULT_TRAFFIC_STRESS_RECIPE } from "@/components/Map/trafficStressExpression";
import { BICYCLE_INFRA_LAYER_ID, SAFETY_LAYER_ID, TRAFFIC_STRESS_LAYER_ID, setStaticOverlayFilters } from "./MapView";
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

describe("setStaticOverlayFilters（交通ストレスレシピの追従）", () => {
  it("trafficStressレイヤーのフィルタは渡したレシピに追従する", () => {
    const customRecipe = {
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      base_by_highway: { ...DEFAULT_TRAFFIC_STRESS_RECIPE.base_by_highway, secondary: 1 },
    };
    // 「レベル1を隠す」絞り込み中に、highway=secondaryがどちらの側に分類されるかで
    // レシピが実際に効いているかを検証する。
    const withHiddenLevel1 = hiddenKeys({ trafficStress: ["1"] });

    const mapDefault = fakeMap();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setStaticOverlayFilters(mapDefault as any, withHiddenLevel1, DEFAULT_TRAFFIC_STRESS_RECIPE, DEFAULT_SAFETY_RECIPE);
    const defaultFilter = mapDefault.setFilterCalls.find((c) => c.layerId === TRAFFIC_STRESS_LAYER_ID)!.filter;

    const mapCustom = fakeMap();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setStaticOverlayFilters(mapCustom as any, withHiddenLevel1, customRecipe, DEFAULT_SAFETY_RECIPE);
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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setStaticOverlayFilters(mapDefault as any, withHiddenProhibited, DEFAULT_TRAFFIC_STRESS_RECIPE, DEFAULT_SAFETY_RECIPE);
    const defaultFilter = mapDefault.setFilterCalls.find((c) => c.layerId === BICYCLE_INFRA_LAYER_ID)!.filter;

    const customRecipe = { ...DEFAULT_TRAFFIC_STRESS_RECIPE, designation_adjustment: 3 };
    const mapCustom = fakeMap();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setStaticOverlayFilters(mapCustom as any, withHiddenProhibited, customRecipe, DEFAULT_SAFETY_RECIPE);
    const customFilter = mapCustom.setFilterCalls.find((c) => c.layerId === BICYCLE_INFRA_LAYER_ID)!.filter;

    expect(customFilter).toEqual(defaultFilter);
  });
});

// 安全度も交通ストレスと同じ理由でレシピに追従する（改善計画: 安全度レシピ）。
describe("setStaticOverlayFilters（安全度レシピの追従）", () => {
  it("safetyレイヤーのフィルタは渡したレシピに追従する", () => {
    const customRecipe = {
      ...DEFAULT_SAFETY_RECIPE,
      base_by_highway: { ...DEFAULT_SAFETY_RECIPE.base_by_highway, secondary: 1 },
    };
    const withHiddenLevel1 = hiddenKeys({ safety: ["1"] });

    const mapDefault = fakeMap();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setStaticOverlayFilters(mapDefault as any, withHiddenLevel1, DEFAULT_TRAFFIC_STRESS_RECIPE, DEFAULT_SAFETY_RECIPE);
    const defaultFilter = mapDefault.setFilterCalls.find((c) => c.layerId === SAFETY_LAYER_ID)!.filter;

    const mapCustom = fakeMap();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setStaticOverlayFilters(mapCustom as any, withHiddenLevel1, DEFAULT_TRAFFIC_STRESS_RECIPE, customRecipe);
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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setStaticOverlayFilters(mapDefault as any, withHiddenProhibited, DEFAULT_TRAFFIC_STRESS_RECIPE, DEFAULT_SAFETY_RECIPE);
    const defaultFilter = mapDefault.setFilterCalls.find((c) => c.layerId === BICYCLE_INFRA_LAYER_ID)!.filter;

    const customRecipe = { ...DEFAULT_SAFETY_RECIPE, designation_adjustment: 3 };
    const mapCustom = fakeMap();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setStaticOverlayFilters(mapCustom as any, withHiddenProhibited, DEFAULT_TRAFFIC_STRESS_RECIPE, customRecipe);
    const customFilter = mapCustom.setFilterCalls.find((c) => c.layerId === BICYCLE_INFRA_LAYER_ID)!.filter;

    expect(customFilter).toEqual(defaultFilter);
  });
});

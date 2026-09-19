// このファイルはMapView.tsxのensure*Layer関数経由でregionApi.ts: accidentTileUrl()等の
// window.location参照コードを実行する（改善計画: environmentMatchGlobs修正）ため、他の
// Map/*.test.tsと違いjsdom環境が必要（既定のまま。node環境docblockを付けない）。
import { createExpression } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";
import { DEDICATED_WAY_VALUE_AXES, RAMP_AXES, axisLineLayerId } from "@/components/Map/axisLayers";
import {
  DESIGNATION_LAYER_ID,
  STOP_POI_LAYER_ID,
  SUPPLY_POI_LAYER_ID,
  buildAxisOverlayLayers,
  buildInteractiveLayerIds,
  buildStaticOverlayLayers,
  layersUnderRoadSurface,
  sortedByPaintTier,
  setStaticOverlayFilters,
} from "./MapView";
import { buildStaticFilterAxes, type StaticFilterAxisId } from "./staticAttributeLayers";
import { buildMapLayers, MAP_LAYER_PAINT_TIER_ORDER } from "./mapLayers";
import { isAreaLayerType } from "./mapStyleOps";

// ビルド時静的フォールバック（RAMP_AXES、軸スタジオが公開したGUI作成軸を含まない）を
// 入力に組み立てた結果。以前のSTATIC_OVERLAY_LAYERS/STATIC_FILTER_AXES定数と同じ内容。
const CATALOG = buildMapLayers(RAMP_AXES, DEDICATED_WAY_VALUE_AXES);
const STATIC_OVERLAY_LAYERS = buildStaticOverlayLayers(
  CATALOG,
  buildAxisOverlayLayers(RAMP_AXES),
  DEDICATED_WAY_VALUE_AXES,
);
const STATIC_FILTER_AXES = buildStaticFilterAxes(RAMP_AXES);

// setStaticOverlayFiltersが読む最小限のmapフェイク。__rcStyleReady=trueでrunWhenStyleReadyの
// 即時実行分岐を通す（MapView.dataStatus.test.tsのfakeMapと同じ発想）。
function fakeMap() {
  const layers = new Set<string>();
  const sources = new Set<string>();
  const setFilterCalls: { layerId: string; filter: unknown }[] = [];
  const addedSpecs: { id: string; type?: string }[] = [];
  return {
    __rcStyleReady: true,
    addedSpecs,
    getLayer: (id: string) => (layers.has(id) ? {} : undefined),
    addLayer: (spec: { id: string; type?: string }) => {
      addedSpecs.push(spec);
      layers.add(spec.id);
    },
    getSource: (id: string) => (sources.has(id) ? {} : undefined),
    addSource: (id: string) => sources.add(id),
    setFilter: (layerId: string, filter: unknown) => setFilterCalls.push({ layerId, filter }),
    setPaintProperty: () => {},
    setLayoutProperty: () => {},
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
function hiddenKeys(
  partial: Partial<Record<StaticFilterAxisId, readonly string[]>>,
): Record<StaticFilterAxisId, readonly string[]> {
  return partial as Record<StaticFilterAxisId, readonly string[]>;
}

// 改善計画T292: 車ストレス（車の圧迫感）は専用Pythonレシピの廃止に伴い、他の推定軸
// （停止密度・事故密度等）と同じ汎用ramp機構（axis:car_stress、axisLineLayerId経由）へ
// 統合された。setStaticOverlayFiltersはレシピ引数を取らなくなり、車の圧迫感専用の
// フィルタ差し替えロジックも不要になった（STATIC_FILTER_AXESの静的なlegendをそのまま使う）。
describe("setStaticOverlayFilters（改善計画T292: 車の圧迫感を含むramp軸の汎用フィルタ適用）", () => {
  it("指定路線レイヤーのフィルタは指定した非表示キーを反映する", () => {
    const map = fakeMap();
    setStaticOverlayFilters(
      map as unknown as Parameters<typeof setStaticOverlayFilters>[0],
      hiddenKeys({ designation: ["emergency_transport"] }),
      STATIC_OVERLAY_LAYERS,
      STATIC_FILTER_AXES,
    );

    const filter = map.setFilterCalls.find((c) => c.layerId === DESIGNATION_LAYER_ID)!.filter;
    expect(evaluateFilter(filter, { designation: "emergency_transport" })).toBe(false);
    expect(evaluateFilter(filter, { designation: "critical_logistics" })).toBe(true);
  });

  it("車の圧迫感（axis:car_stress）のrampレイヤーにもフィルタが設定される", () => {
    const map = fakeMap();
    setStaticOverlayFilters(
      map as unknown as Parameters<typeof setStaticOverlayFilters>[0],
      hiddenKeys({}),
      STATIC_OVERLAY_LAYERS,
      STATIC_FILTER_AXES,
    );

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
    setStaticOverlayFilters(
      map as unknown as Parameters<typeof setStaticOverlayFilters>[0],
      hiddenKeys({}),
      STATIC_OVERLAY_LAYERS,
      STATIC_FILTER_AXES,
    );
    const filter = map.setFilterCalls.find((c) => c.layerId === STOP_POI_LAYER_ID)!.filter;

    expect(evaluateFilter(filter, { kind: "traffic_signals" })).toBe(true);
    expect(evaluateFilter(filter, { kind: "convenience" })).toBe(false);
  });

  it("supplyPoiレイヤーのフィルタはsupplyPoi側のkindのみ通し、stopPoi側のkindは弾く", () => {
    const map = fakeMap();
    setStaticOverlayFilters(
      map as unknown as Parameters<typeof setStaticOverlayFilters>[0],
      hiddenKeys({}),
      STATIC_OVERLAY_LAYERS,
      STATIC_FILTER_AXES,
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
      map as unknown as Parameters<typeof setStaticOverlayFilters>[0],
      withHiddenTrafficSignals,
      STATIC_OVERLAY_LAYERS,
      STATIC_FILTER_AXES,
    );
    const supplyFilter = map.setFilterCalls.find((c) => c.layerId === SUPPLY_POI_LAYER_ID)!.filter;

    expect(evaluateFilter(supplyFilter, { kind: "traffic_signals" })).toBe(false);
    expect(evaluateFilter(supplyFilter, { kind: "convenience" })).toBe(true);
  });
});

// 改善計画T478（統合レビュー第3回§9指摘の再確認）: buildInteractiveLayerIdsが
// interactive=falseのエントリ（専用ポップアップを持たないレイヤー）を除外できていないと、
// handleMouseMove（同じinteractiveLayerIdsを参照）がそのレイヤー上でpointerカーソルを
// 出してしまい、「カーソルはクリック可能を示すのに実際は何も起きない」という不整合になる。
describe("buildInteractiveLayerIds（改善計画T478）", () => {
  it("interactive=falseのエントリは1つも含まれない（クリックしても何も起きないため、hoverでpointerカーソルも出してはいけない）", () => {
    const ids = buildInteractiveLayerIds(STATIC_OVERLAY_LAYERS);
    const nonInteractive = STATIC_OVERLAY_LAYERS.filter((layer) => !layer.interactive);
    expect(nonInteractive.length).toBeGreaterThan(0);
    for (const layer of nonInteractive) expect(ids).not.toContain(layer.layerId);
  });

  it("designation等の通常の道路属性レイヤーは引き続きinteractiveLayerIdsに含まれる（road_surfaceと同じ道路属性を持つため専用ポップアップが機能する）", () => {
    const ids = buildInteractiveLayerIds(STATIC_OVERLAY_LAYERS);
    expect(ids).toContain(DESIGNATION_LAYER_ID);
  });
});

// 表示ON/OFFのたびに走る`ensure`（setStaticOverlayVisibilityが全レイヤーへ呼ぶ）が、
// 凡例のON/OFFから組み立てた絞り込みを巻き戻していた（paintについて同じ構造をT712で
// 直したが、filterに残っていた）。`ensure`は表示切替のたびに走るため、症状は
// 「チップを切り替えると絞り込みが勝手に戻る」という形で出る。
describe("凡例フィルタはensureの再実行で巻き戻らない", () => {
  it("フィルタ適用後にlayer.ensure(map)を呼んでも、setFilterが上書きされない", () => {
    const map = fakeMap();
    setStaticOverlayFilters(
      map as unknown as Parameters<typeof setStaticOverlayFilters>[0],
      hiddenKeys({ designation: ["emergency_transport"] }),
      STATIC_OVERLAY_LAYERS,
      STATIC_FILTER_AXES,
    );
    const applied = map.setFilterCalls.filter((call) => call.layerId === DESIGNATION_LAYER_ID);
    expect(applied.length).toBe(1);
    expect(applied[0].filter).toBeDefined();

    const designation = STATIC_OVERLAY_LAYERS.find((layer) => layer.key === "designation")!;
    designation.ensure(map as unknown as Parameters<typeof designation.ensure>[0]);

    expect(map.setFilterCalls.filter((call) => call.layerId === DESIGNATION_LAYER_ID)).toEqual(applied);
  });

  it("ramp軸レイヤーでも同じ", () => {
    const map = fakeMap();
    const axis = RAMP_AXES[0];
    setStaticOverlayFilters(
      map as unknown as Parameters<typeof setStaticOverlayFilters>[0],
      hiddenKeys({}),
      STATIC_OVERLAY_LAYERS,
      STATIC_FILTER_AXES,
    );
    const layerId = axisLineLayerId(axis.axisId);
    const applied = map.setFilterCalls.filter((call) => call.layerId === layerId);
    expect(applied.length).toBe(1);

    const entry = STATIC_OVERLAY_LAYERS.find((layer) => layer.layerId === layerId)!;
    entry.ensure(map as unknown as Parameters<typeof entry.ensure>[0]);

    expect(map.setFilterCalls.filter((call) => call.layerId === layerId)).toEqual(applied);
  });
});

describe("重なりの段", () => {
  it("作る側がどの順で並べても、重なりは段の順になる", () => {
    // **作る側の配列の並びを見ても、並べ替えが効いているかは分からない**——今の並びは
    // たまたま段の順と一致しているため、並べ替えを外しても結果が変わらない。効いて
    // いることを見るには、段の順と食い違う並びを通す必要がある。
    const shuffled = [...STATIC_OVERLAY_LAYERS].reverse();
    const tiers = sortedByPaintTier(shuffled).map((layer) => MAP_LAYER_PAINT_TIER_ORDER.indexOf(layer.paintTier));

    expect(tiers.length).toBeGreaterThan(0);
    expect([...tiers].sort((a, b) => a - b)).toEqual(tiers);
  });

  it("同じ段の中では、カタログに現れる順を保つ", () => {
    // 段だけでは前後が決まらない組（観測の線どうし等）は、カタログの並びが決める。
    const rawLines = STATIC_OVERLAY_LAYERS.filter((layer) => layer.paintTier === "rawLine").map((l) => l.key);
    const inCatalog = CATALOG.filter((layer) => rawLines.includes(layer.id)).map((layer) => layer.id);

    expect(rawLines.length).toBeGreaterThan(1);
    expect(rawLines).toEqual(inCatalog);
  });

  it("面で塗るレイヤーはすべて路面ソースより先に積まれる", () => {
    // 初回描画では、ここで選ばれたレイヤーだけが路面ソースより前に積まれる。選ばれない
    // 面のレイヤーは初回だけ路面線の上に乗り、再描画で下へ戻る（T886で実際に起きた）。
    //
    // **母集団は「実際に地図へ積まれるレイヤーの型」から導く**。記述子の`paintTier`だけで
    // 両辺を作ると、宣言を書き換えても両辺が一緒に動くため落ちない（名指しで2件並べて
    // いた元の形と同じく、起伏が抜けても気づけない）。
    const map = fakeMap();
    for (const entry of STATIC_OVERLAY_LAYERS) {
      entry.ensure(map as unknown as Parameters<typeof entry.ensure>[0]);
    }
    const typeByLayerId = new Map(map.addedSpecs.map((spec) => [spec.id, spec.type ?? ""]));
    const paintsArea = STATIC_OVERLAY_LAYERS.filter((entry) =>
      isAreaLayerType(typeByLayerId.get(entry.layerId) ?? ""),
    ).map((entry) => entry.key);
    const hoisted = layersUnderRoadSurface(STATIC_OVERLAY_LAYERS).map((layer) => layer.key);

    expect(paintsArea.length).toBeGreaterThan(0);
    expect([...hoisted].sort()).toEqual([...paintsArea].sort());
    // 線のレイヤーは路面ソースを共有するため、先に積むと「source not found」になる。
    expect(hoisted).not.toContain("designation");
  });
});

describe("クリックできる場所とカーソルが変わる場所", () => {
  it("ルート系の当たり判定レイヤーも対象に入る", () => {
    // handleClickが専用ハンドラへ任せるレイヤー（候補線・乗り換え帯）は、利用者から見れば
    // クリックできる場所である。カーソルの一覧から外れていると「押せるのにカーソルが
    // 変わらない」という、この関数が防ぐと宣言している非対称がそのまま起きる。
    const ids = buildInteractiveLayerIds(STATIC_OVERLAY_LAYERS);

    expect(ids).toContain("route-candidates-hit");
    expect(ids).toContain("route-splice-stretches-hit");
    expect(ids).toContain("route-detail-segments-hit");
  });
});

// @vitest-environment node
import { describe, expect, it } from "vitest";
import { RAMP_AXES } from "./axisLayers";
import { buildLayerDataSources, ROAD_TILE_SOURCE_ID } from "./MapView";
import { buildMapLayers } from "./mapLayers";
import { ROAD_TILE_MIN_ZOOM } from "@/services/regionApi";
import { clearStaleTrackedSourceErrors, computeLayerDataStatus } from "./useLayerDataStatus";
import { createFakeDataStatusMap } from "@/testing/fakeDataStatusMap";

// ビルド時静的フォールバック（RAMP_AXES、軸スタジオが公開したGUI作成軸を含まない）を
// 入力に組み立てた結果。以前のLAYER_DATA_SOURCES/ROAD_SURFACE_SHARED_LAYER_IDS定数と
// 同じ内容。
const LAYER_DATA_SOURCES = buildLayerDataSources(RAMP_AXES);

const fakeMap = createFakeDataStatusMap(LAYER_DATA_SOURCES.map((e) => e.sourceId));

function sourceIdFor(key: string): string {
  return LAYER_DATA_SOURCES.find((e) => e.key === key)!.sourceId;
}

describe("computeLayerDataStatus", () => {
  it("表示OFFのレイヤーはキー自体を持たない", () => {
    const map = fakeMap({});
    const status = computeLayerDataStatus(map, new Set(), { "axis:car_stress": false }, LAYER_DATA_SOURCES);
    expect(status).toEqual({});
  });

  it("ソース未追加（初期化直後）のレイヤーもキー自体を持たない", () => {
    const map = fakeMap({ addedSourceIds: [] });
    const status = computeLayerDataStatus(map, new Set(), { "axis:car_stress": true }, LAYER_DATA_SOURCES);
    expect(status).toEqual({});
  });

  it("タイル取得中（isSourceLoaded=false）はloading", () => {
    const map = fakeMap({ unloadedSourceIds: [sourceIdFor("accidents")] });
    const status = computeLayerDataStatus(map, new Set(), { accidents: true }, LAYER_DATA_SOURCES);
    expect(status).toEqual({ accidents: "loading" });
  });

  it("読込済みだが対象source-layerのフィーチャーが0件のときはempty", () => {
    const map = fakeMap({
      emptySourceLayers: [{ sourceId: sourceIdFor("stopPoi"), sourceLayer: "stop_poi" }],
    });
    const status = computeLayerDataStatus(map, new Set(), { stopPoi: true }, LAYER_DATA_SOURCES);
    expect(status).toEqual({ stopPoi: "empty" });
  });

  it("erroredSourceIdsに含まれるsourceはisSourceLoaded/querySourceFeaturesの結果に関わらずerror", () => {
    const map = fakeMap({});
    const status = computeLayerDataStatus(map, new Set([sourceIdFor("accidents")]), { accidents: true }, LAYER_DATA_SOURCES);
    expect(status).toEqual({ accidents: "error" });
  });

  it("読込済みかつフィーチャーがあれば正常（キー自体を持たない）", () => {
    const map = fakeMap({});
    const status = computeLayerDataStatus(map, new Set(), { "axis:car_stress": true }, LAYER_DATA_SOURCES);
    expect(status).toEqual({});
  });

  it("roadType/roadSurface/axis:car_stress/designationは同じroad_surfaceタイルを再利用するため、同時にemptyになる（road_edges未構築地点を想定）", () => {
    const map = fakeMap({
      emptySourceLayers: [{ sourceId: sourceIdFor("roadType"), sourceLayer: "road_surface" }],
    });
    const status = computeLayerDataStatus(
      map,
      new Set(),
      { roadType: true, roadSurface: true, "axis:car_stress": true, designation: true },
      LAYER_DATA_SOURCES,
    );
    expect(status).toEqual({
      roadType: "empty",
      roadSurface: "empty",
      "axis:car_stress": "empty",
      designation: "empty",
    });
  });

  it("elevation（ラスタ、source-layer無し）はエラー時のみerrorになり、emptyにはならない", () => {
    const map = fakeMap({});
    const ok = computeLayerDataStatus(map, new Set(), { elevation: true }, LAYER_DATA_SOURCES);
    expect(ok).toEqual({});
    const errored = computeLayerDataStatus(map, new Set([sourceIdFor("elevation")]), { elevation: true }, LAYER_DATA_SOURCES);
    expect(errored).toEqual({ elevation: "error" });
  });

  // レビュー指摘: roadType/roadSurface/axis:car_stress/designationが同じ
  // (sourceId, sourceLayer)を共有するため、素朴に実装するとquerySourceFeaturesが同じ引数で
  // 複数回呼ばれていた（road_surfaceは実測6,273件、sourcedata等の高頻度イベントのたびに
  // 呼ばれるため無視できないコスト）。1回のcomputeLayerDataStatus呼び出し内では
  // (sourceId, sourceLayer)ペアごとに1回だけ呼ぶことを確認する。
  it("同じ(sourceId, sourceLayer)を共有する4レイヤーが同時に見えていても、querySourceFeaturesは1回しか呼ばれない", () => {
    const calls: { sourceId: string; sourceLayer: string }[] = [];
    const map = fakeMap({ querySourceFeaturesCalls: calls });
    computeLayerDataStatus(
      map,
      new Set(),
      { roadType: true, roadSurface: true, "axis:car_stress": true, designation: true },
      LAYER_DATA_SOURCES,
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({ sourceId: sourceIdFor("roadType"), sourceLayer: "road_surface" });
  });

  it("別の(sourceId, sourceLayer)を持つレイヤーはそれぞれ個別にquerySourceFeaturesが呼ばれる", () => {
    const calls: { sourceId: string; sourceLayer: string }[] = [];
    const map = fakeMap({ querySourceFeaturesCalls: calls });
    computeLayerDataStatus(map, new Set(), { roadType: true, stopPoi: true, accidents: true }, LAYER_DATA_SOURCES);
    expect(calls).toHaveLength(3);
  });
});

describe("clearStaleTrackedSourceErrors", () => {
  // 実機確認（2026-08-16）で発見: バックエンド障害中に別地点でerrorが記録された後、
  // 障害復旧後に既にタイルがキャッシュ済みの地点（新規の取得サイクルが一度も
  // 発生しない）へ戻ると、sourcedataloadingを待つだけの解除条件では永久にエラー表示が
  // 残ってしまっていた。moveend/zoomend（パン/ズームが収束した時点）で、保留中の
  // 取得が無いsource（isSourceLoaded=true）は「このビューポートでは問題無し」として
  // 解除する。
  it("isSourceLoaded=trueのsourceはerroredSourceIdsから取り除かれ、変更があったことをtrueで返す", () => {
    const map = fakeMap({});
    const errored = new Set([sourceIdFor("accidents"), sourceIdFor("stopPoi")]);
    const changed = clearStaleTrackedSourceErrors(map, errored);
    expect(changed).toBe(true);
    expect(errored.size).toBe(0);
  });

  it("isSourceLoaded=falseのまま（取得中）のsourceは取り除かれない", () => {
    const map = fakeMap({ unloadedSourceIds: [sourceIdFor("accidents")] });
    const errored = new Set([sourceIdFor("accidents")]);
    const changed = clearStaleTrackedSourceErrors(map, errored);
    expect(changed).toBe(false);
    expect(errored.has(sourceIdFor("accidents"))).toBe(true);
  });

  it("erroredSourceIdsが空のときは変更なしでfalseを返す", () => {
    const map = fakeMap({});
    const errored = new Set<string>();
    expect(clearStaleTrackedSourceErrors(map, errored)).toBe(false);
  });
});

describe("路面タイルの最小ズーム", () => {
  it("路面タイルを読むチップ付きレイヤーは、記述子にその最小ズームを宣言している", () => {
    // 宣言が無いレイヤーは、ONにしても何も出ない理由が画面から消える。同じタイルを
    // 共有する他のレイヤーには案内が出るぶん、抜けに気づきにくい。
    const byId = Object.fromEntries(buildMapLayers([], []).map((layer) => [layer.id, layer]));
    const readsRoadTile = LAYER_DATA_SOURCES.filter((entry) => entry.sourceId === ROAD_TILE_SOURCE_ID)
      .map((entry) => entry.key)
      .filter((key) => key in byId);
    expect(readsRoadTile.length).toBeGreaterThan(0);

    for (const key of readsRoadTile) {
      expect(byId[key].tileMinZoom).toBe(ROAD_TILE_MIN_ZOOM);
    }
  });
});

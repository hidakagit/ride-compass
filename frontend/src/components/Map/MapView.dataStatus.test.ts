import { describe, expect, it } from "vitest";
import {
  LAYER_DATA_SOURCES,
  clearStaleTrackedSourceErrors,
  computeLayerDataStatus,
  isRoadSurfaceGroupVisible,
} from "./MapView";

// computeLayerDataStatus（改善計画T87）が読む3メソッドだけを持つフェイクmap。
// getSourceは「そのsourceが追加済みか」、isSourceLoadedは「保留中のタイル要求が無いか」、
// querySourceFeaturesは「現在読み込み済みのタイル内のフィーチャー数」を模す。
// querySourceFeaturesCallsを渡すと呼び出しごとの引数を記録する（メモ化の検証用）。
function fakeMap(options: {
  addedSourceIds?: readonly string[];
  unloadedSourceIds?: readonly string[];
  emptySourceLayers?: readonly { sourceId: string; sourceLayer: string }[];
  querySourceFeaturesCalls?: { sourceId: string; sourceLayer: string }[];
}) {
  const addedSourceIds = new Set(options.addedSourceIds ?? LAYER_DATA_SOURCES.map((e) => e.sourceId));
  const unloadedSourceIds = new Set(options.unloadedSourceIds ?? []);
  const emptyKeys = new Set((options.emptySourceLayers ?? []).map((e) => `${e.sourceId}::${e.sourceLayer}`));
  return {
    getSource: (id: string) => (addedSourceIds.has(id) ? {} : undefined),
    isSourceLoaded: (id: string) => !unloadedSourceIds.has(id),
    querySourceFeatures: (id: string, { sourceLayer }: { sourceLayer: string }) => {
      options.querySourceFeaturesCalls?.push({ sourceId: id, sourceLayer });
      return emptyKeys.has(`${id}::${sourceLayer}`) ? [] : [{ type: "Feature" }];
    },
  };
}

function sourceIdFor(key: string): string {
  return LAYER_DATA_SOURCES.find((e) => e.key === key)!.sourceId;
}

describe("computeLayerDataStatus", () => {
  it("表示OFFのレイヤーはキー自体を持たない", () => {
    const map = fakeMap({});
    const status = computeLayerDataStatus(map, new Set(), { trafficStress: false });
    expect(status).toEqual({});
  });

  it("ソース未追加（初期化直後）のレイヤーもキー自体を持たない", () => {
    const map = fakeMap({ addedSourceIds: [] });
    const status = computeLayerDataStatus(map, new Set(), { trafficStress: true });
    expect(status).toEqual({});
  });

  it("タイル取得中（isSourceLoaded=false）はloading", () => {
    const map = fakeMap({ unloadedSourceIds: [sourceIdFor("accidents")] });
    const status = computeLayerDataStatus(map, new Set(), { accidents: true });
    expect(status).toEqual({ accidents: "loading" });
  });

  it("読込済みだが対象source-layerのフィーチャーが0件のときはempty", () => {
    const map = fakeMap({
      emptySourceLayers: [{ sourceId: sourceIdFor("stopPoi"), sourceLayer: "stop_poi" }],
    });
    const status = computeLayerDataStatus(map, new Set(), { stopPoi: true });
    expect(status).toEqual({ stopPoi: "empty" });
  });

  it("erroredSourceIdsに含まれるsourceはisSourceLoaded/querySourceFeaturesの結果に関わらずerror", () => {
    const map = fakeMap({});
    const status = computeLayerDataStatus(map, new Set([sourceIdFor("accidents")]), { accidents: true });
    expect(status).toEqual({ accidents: "error" });
  });

  it("読込済みかつフィーチャーがあれば正常（キー自体を持たない）", () => {
    const map = fakeMap({});
    const status = computeLayerDataStatus(map, new Set(), { trafficStress: true });
    expect(status).toEqual({});
  });

  it("T54のようにosm_raw_poisだけ未取込の場合、同じソースでもsource-layerが別のintersectionsは影響を受けない", () => {
    const map = fakeMap({
      emptySourceLayers: [{ sourceId: sourceIdFor("stopPoi"), sourceLayer: "stop_poi" }],
    });
    const status = computeLayerDataStatus(map, new Set(), { stopPoi: true, intersections: true });
    expect(status).toEqual({ stopPoi: "empty" });
  });

  it("road/trafficStress/bicycleInfra/designationは同じroad_surfaceタイルを再利用するため、同時にemptyになる（road_edges未構築地点を想定）", () => {
    const map = fakeMap({
      emptySourceLayers: [{ sourceId: sourceIdFor("road"), sourceLayer: "road_surface" }],
    });
    const status = computeLayerDataStatus(map, new Set(), {
      road: true,
      trafficStress: true,
      bicycleInfra: true,
      designation: true,
    });
    expect(status).toEqual({ road: "empty", trafficStress: "empty", bicycleInfra: "empty", designation: "empty" });
  });

  it("elevation（ラスタ、source-layer無し）はエラー時のみerrorになり、emptyにはならない", () => {
    const map = fakeMap({});
    const ok = computeLayerDataStatus(map, new Set(), { elevation: true });
    expect(ok).toEqual({});
    const errored = computeLayerDataStatus(map, new Set([sourceIdFor("elevation")]), { elevation: true });
    expect(errored).toEqual({ elevation: "error" });
  });

  // レビュー指摘: road/trafficStress/bicycleInfra/designationが同じ(sourceId, sourceLayer)を
  // 共有するため、素朴に実装するとquerySourceFeaturesが同じ引数で4回呼ばれていた
  // （road_surfaceは実測6,273件、sourcedata等の高頻度イベントのたびに呼ばれるため無視できない
  // コスト）。1回のcomputeLayerDataStatus呼び出し内では(sourceId, sourceLayer)ペアごとに
  // 1回だけ呼ぶことを確認する。
  it("同じ(sourceId, sourceLayer)を共有する4レイヤーが同時に見えていても、querySourceFeaturesは1回しか呼ばれない", () => {
    const calls: { sourceId: string; sourceLayer: string }[] = [];
    const map = fakeMap({ querySourceFeaturesCalls: calls });
    computeLayerDataStatus(map, new Set(), {
      road: true,
      trafficStress: true,
      bicycleInfra: true,
      designation: true,
    });
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({ sourceId: sourceIdFor("road"), sourceLayer: "road_surface" });
  });

  it("別の(sourceId, sourceLayer)を持つレイヤーはそれぞれ個別にquerySourceFeaturesが呼ばれる", () => {
    const calls: { sourceId: string; sourceLayer: string }[] = [];
    const map = fakeMap({ querySourceFeaturesCalls: calls });
    computeLayerDataStatus(map, new Set(), { road: true, stopPoi: true, accidents: true });
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

describe("isRoadSurfaceGroupVisible", () => {
  // レビュー指摘: 以前はregionZoomTooWideがroadのvisibilityだけを見ていたため、
  // road自体はOFFのままtrafficStress等だけONで表示範囲が広すぎる場合に、
  // ズーム範囲外の案内が一切出ない不整合があった。road_surfaceタイルを共有する
  // 4レイヤー（road/trafficStress/bicycleInfra/designation）のいずれか1つでもONなら
  // trueを返すことを確認する。
  it("road/trafficStress/bicycleInfra/designationのいずれか1つでもONならtrue", () => {
    expect(isRoadSurfaceGroupVisible({ road: true })).toBe(true);
    expect(isRoadSurfaceGroupVisible({ trafficStress: true })).toBe(true);
    expect(isRoadSurfaceGroupVisible({ bicycleInfra: true })).toBe(true);
    expect(isRoadSurfaceGroupVisible({ designation: true })).toBe(true);
  });

  it("4レイヤーすべてOFF（road_surfaceを共有しない他レイヤーがONでも）ならfalse", () => {
    expect(isRoadSurfaceGroupVisible({ road: false, trafficStress: false, stopPoi: true, accidents: true })).toBe(
      false,
    );
  });

  it("空のvisibilityオブジェクトはfalse", () => {
    expect(isRoadSurfaceGroupVisible({})).toBe(false);
  });
});

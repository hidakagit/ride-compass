// useLayerDataStatus（T87、フックとしてのrecompute/markSourceErrored等の配線）のテスト。
// computeLayerDataStatus/clearStaleTrackedSourceErrors自体（純粋関数）のテストは
// MapView.dataStatus.test.tsに既にあるため、ここではフック側（メモ化されたrecompute呼び出し
// 経路・エラー解除条件の呼び出し経路配線）に絞る。renderHook（@testing-library/react）は
// react-domのcreateRootを内部で使いDOMを要求するため、既定のDOM環境のまま実行する
// （node環境docblockは付けない。他のrenderHookを使うテスト、例えば
// hooks/useDebouncedValue.test.tsも同様に既定環境のまま）。
import { act, renderHook } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";
import type { LayerDataStatusByLayer, MapLayerId } from "@/components/Map/mapLayers";
import {
  clearStaleTrackedSourceErrors,
  computeLayerDataStatus,
  type DataStatusMapLike,
  type LayerDataSourceEntry,
  useLayerDataStatus,
} from "./useLayerDataStatus";

// MapView.dataStatus.test.tsのfakeMapと同じパターン（computeLayerDataStatusが読む3メソッドだけを
// 持つフェイクmap）。querySourceFeaturesCallsを渡すと呼び出しごとの引数を記録する。
function fakeMap(options: {
  addedSourceIds?: readonly string[];
  unloadedSourceIds?: readonly string[];
  emptySourceLayers?: readonly { sourceId: string; sourceLayer: string }[];
  querySourceFeaturesCalls?: { sourceId: string; sourceLayer: string }[];
}): DataStatusMapLike {
  const addedSourceIds = new Set(options.addedSourceIds ?? []);
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

// road/carStress/tunnel/designationのように複数レイヤーが同じ(sourceId, sourceLayer)を
// 共有する状況を模した最小の対応表。
const SHARED_SOURCE_ID = "road_surface_source";
const SHARED_SOURCE_LAYER = "road_surface";
const SHARED_LAYER_DATA_SOURCES: readonly LayerDataSourceEntry[] = [
  { key: "roadType" as MapLayerId, sourceId: SHARED_SOURCE_ID, sourceLayer: SHARED_SOURCE_LAYER },
  { key: "roadSurface" as MapLayerId, sourceId: SHARED_SOURCE_ID, sourceLayer: SHARED_SOURCE_LAYER },
  { key: "axis:car_stress" as MapLayerId, sourceId: SHARED_SOURCE_ID, sourceLayer: SHARED_SOURCE_LAYER },
  { key: "tunnel" as MapLayerId, sourceId: SHARED_SOURCE_ID, sourceLayer: SHARED_SOURCE_LAYER },
  { key: "designation" as MapLayerId, sourceId: SHARED_SOURCE_ID, sourceLayer: SHARED_SOURCE_LAYER },
];

const ALL_SHARED_KEYS_VISIBLE: Partial<Record<MapLayerId, boolean>> = {
  roadType: true,
  roadSurface: true,
  "axis:car_stress": true,
  tunnel: true,
  designation: true,
};

describe("computeLayerDataStatus のメモ化", () => {
  it("同一の(source, source-layer)を参照する5レイヤーが同時に見えていても、querySourceFeaturesは1回しか呼ばれない", () => {
    const calls: { sourceId: string; sourceLayer: string }[] = [];
    const map = fakeMap({
      addedSourceIds: [SHARED_SOURCE_ID],
      querySourceFeaturesCalls: calls,
    });

    const status = computeLayerDataStatus(map, new Set(), ALL_SHARED_KEYS_VISIBLE, SHARED_LAYER_DATA_SOURCES);

    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({ sourceId: SHARED_SOURCE_ID, sourceLayer: SHARED_SOURCE_LAYER });
    // 呼び出し回数だけでなく、算出結果自体も5レイヤー全てに反映されていることを確認する
    // （メモ化がキャッシュのキー取り違え等で一部のレイヤーだけ結果を落としていないか）。
    expect(status).toEqual({});
  });

  it("useLayerDataStatusフック経由でも、1回のrecomputeにつきquerySourceFeaturesは1回しか呼ばれない", () => {
    const calls: { sourceId: string; sourceLayer: string }[] = [];
    const map = fakeMap({
      addedSourceIds: [SHARED_SOURCE_ID],
      querySourceFeaturesCalls: calls,
    });
    const onChange = vi.fn<(status: LayerDataStatusByLayer) => void>();

    const { result } = renderHook(() => {
      const mapRef = useRef<DataStatusMapLike | null>(map);
      const onChangeRef = useRef(onChange);
      onChangeRef.current = onChange;
      return useLayerDataStatus({
        mapRef,
        layerDataSources: SHARED_LAYER_DATA_SOURCES,
        getVisibility: () => ALL_SHARED_KEYS_VISIBLE,
        onChangeRef,
      });
    });

    act(() => {
      result.current.notifySourceData(SHARED_SOURCE_ID);
    });

    expect(calls).toHaveLength(1);
  });
});

describe("clearStaleTrackedSourceErrors のerror解除条件", () => {
  // 実装コメント（useLayerDataStatus.ts）: 呼び出し元はmoveend/zoomendに限定し、"idle"から
  // 呼んではいけない。isSourceLoaded()は'errored'状態でも「保留中の要求が無い」という理由で
  // trueを返すため、idleでこれを解除条件に使うと進行中の障害を誤って解除してしまう
  // （実機バグ修正）。この関数自体はisSourceLoadedの値のみを見るので、呼び出し元がmoveend/
  // zoomendのタイミングでのみ呼ぶという契約が守られている前提でのテストになる。
  it("isSourceLoaded=trueのときだけerrorが解除される", () => {
    const map = fakeMap({});
    const erroredSourceIds = new Set(["source-a"]);

    const changed = clearStaleTrackedSourceErrors(map, erroredSourceIds);

    expect(changed).toBe(true);
    expect(erroredSourceIds.has("source-a")).toBe(false);
  });

  it("isSourceLoaded=falseのとき（進行中の障害）はerrorが解除されない", () => {
    const map = fakeMap({ unloadedSourceIds: ["source-a"] });
    const erroredSourceIds = new Set(["source-a"]);

    const changed = clearStaleTrackedSourceErrors(map, erroredSourceIds);

    expect(changed).toBe(false);
    expect(erroredSourceIds.has("source-a")).toBe(true);
  });

  it("複数sourceのうち、isSourceLoaded=trueのものだけが個別に解除される（false側は残る）", () => {
    const map = fakeMap({ unloadedSourceIds: ["source-loading"] });
    const erroredSourceIds = new Set(["source-loaded", "source-loading"]);

    const changed = clearStaleTrackedSourceErrors(map, erroredSourceIds);

    expect(changed).toBe(true);
    expect(erroredSourceIds.has("source-loaded")).toBe(false);
    expect(erroredSourceIds.has("source-loading")).toBe(true);
  });

  it("useLayerDataStatusのsettleViewportは、isSourceLoaded=trueのsourceに対してerroredSourceIdsを解除しonChangeを呼ぶ", () => {
    const map = fakeMap({ addedSourceIds: [SHARED_SOURCE_ID] });
    const onChange = vi.fn<(status: LayerDataStatusByLayer) => void>();

    const { result } = renderHook(() => {
      const mapRef = useRef<DataStatusMapLike | null>(map);
      const onChangeRef = useRef(onChange);
      onChangeRef.current = onChange;
      return useLayerDataStatus({
        mapRef,
        layerDataSources: SHARED_LAYER_DATA_SOURCES,
        getVisibility: () => ALL_SHARED_KEYS_VISIBLE,
        onChangeRef,
      });
    });

    // 'error'イベント相当でエラーを記録した状態を作る。
    act(() => {
      result.current.markSourceErrored(SHARED_SOURCE_ID);
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ roadType: "error", roadSurface: "error", "axis:car_stress": "error", tunnel: "error", designation: "error" }),
    );
    onChange.mockClear();

    // moveend/zoomend相当（isSourceLoaded=trueのまま）でsettleViewportを呼ぶと解除される。
    act(() => {
      result.current.settleViewport();
    });
    expect(onChange).toHaveBeenLastCalledWith(expect.not.objectContaining({ roadType: "error" }));
  });

  it("useLayerDataStatusのsettleViewportは、isSourceLoaded=falseの間はerrorを解除せずonChangeも呼ばない", () => {
    const map = fakeMap({ addedSourceIds: [SHARED_SOURCE_ID], unloadedSourceIds: [SHARED_SOURCE_ID] });
    const onChange = vi.fn<(status: LayerDataStatusByLayer) => void>();

    const { result } = renderHook(() => {
      const mapRef = useRef<DataStatusMapLike | null>(map);
      const onChangeRef = useRef(onChange);
      onChangeRef.current = onChange;
      return useLayerDataStatus({
        mapRef,
        layerDataSources: SHARED_LAYER_DATA_SOURCES,
        getVisibility: () => ALL_SHARED_KEYS_VISIBLE,
        onChangeRef,
      });
    });

    act(() => {
      result.current.markSourceErrored(SHARED_SOURCE_ID);
    });
    onChange.mockClear();

    act(() => {
      result.current.settleViewport();
    });
    // isSourceLoaded=falseのため解除条件を満たさず、changed=falseでrecomputeが呼ばれない
    // （onChangeが呼ばれない）ことを確認する。
    expect(onChange).not.toHaveBeenCalled();
  });
});

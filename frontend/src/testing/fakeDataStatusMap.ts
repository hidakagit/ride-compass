import type { DataStatusMapLike } from "@/components/Map/useLayerDataStatus";

interface FakeMapOptions {
  addedSourceIds?: readonly string[];
  unloadedSourceIds?: readonly string[];
  emptySourceLayers?: readonly { sourceId: string; sourceLayer: string }[];
  querySourceFeaturesCalls?: { sourceId: string; sourceLayer: string }[];
}

/**
 * `computeLayerDataStatus`が読む3メソッドだけを持つフェイクmapを作る関数を返す。
 *
 * `getSource`は「そのsourceが追加済みか」、`isSourceLoaded`は「保留中のタイル要求が
 * 無いか」、`querySourceFeatures`は「読み込み済みタイル内のフィーチャー数」を模す。
 * `querySourceFeaturesCalls`を渡すと呼び出しごとの引数が記録される（メモ化の検証用）。
 *
 * 既定で追加済みと見なすsourceはテストごとに違うため、ファクトリの引数で受け取る。
 */
export function createFakeDataStatusMap(defaultAddedSourceIds: readonly string[]) {
  return function fakeMap(options: FakeMapOptions): DataStatusMapLike {
    const addedSourceIds = new Set(options.addedSourceIds ?? defaultAddedSourceIds);
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
  };
}
